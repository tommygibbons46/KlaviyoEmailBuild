import os, json, datetime
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests

# 1. Broad bot scope is the most stable for Service Accounts
SCOPES = ['https://www.googleapis.com/auth/chat.bot']

def get_chat_ideas():
    creds_dict = json.loads(os.environ['GCHAT_CREDS'])
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    chat = build('chat', 'v1', credentials=creds)
    
    space_id = os.environ['GCHAT_SPACE']
    if not space_id.startswith('spaces/'):
        space_id = f"spaces/{space_id}"
        
    result = chat.spaces().messages().list(parent=space_id).execute()
    messages = result.get('messages', [])
    
    # Filter for messages with #news or ideas from the last 7 days
    raw_text = [m['text'] for m in messages if "#news" in m.get('text', '').lower()]
    return "\n".join(raw_text)

def generate_newsletter_html(raw_ideas):
    genai.configure(api_key=os.environ['GEMINI_KEY'])
    model = genai.GenerativeModel('gemini-1.5-pro')
    prompt = f"""
    Context: You are the brand voice for Hempitecture. 
    Tone: Innovative, grounded, expert yet accessible.
    Task: Synthesize these team notes into a 3-section email draft: 
    1. 'The Build', 2. 'Carbon Impact', 3. 'Team News'.
    Raw Notes: {raw_ideas}
    Output: Return ONLY the raw HTML for the email body.
    """
    response = model.generate_content(prompt)
    return response.text

def create_klaviyo_draft(html_content):
    headers = {
        "Authorization": f"Klaviyo-API-Key {os.environ['KLAVIYO_KEY']}",
        "revision": "2024-02-15",
        "accept": "application/json",
        "content-type": "application/json"
    }

    # Step A: Create the Campaign Shell
    url = "https://a.klaviyo.com/api/campaigns/"
    payload = {
        "data": {
            "type": "campaign",
            "attributes": {
                "name": f"Weekly Draft: {datetime.date.today()}",
                "audiences": {"included": [os.environ['KLAVIYO_LIST']]},
                "campaign_type": "email",
                "template_id": "V5BEw8" # Your Hempitecture Template
            }
        }
    }
    
    resp = requests.post(url, json=payload, headers=headers).json()
    if 'data' not in resp:
        return resp
        
    campaign_id = resp['data']['id']

    # Step B: Inject Gemini's HTML into the campaign's message
    msg_url = f"https://a.klaviyo.com/api/campaigns/{campaign_id}/campaign-messages/"
    msg_data = requests.get(msg_url, headers=headers).json()
    msg_id = msg_data['data'][0]['id']

    patch_url = f"https://a.klaviyo.com/api/campaign-messages/{msg_id}/"
    patch_payload = {
        "data": {
            "type": "campaign-message",
            "id": msg_id,
            "attributes": {
                "content": {
                    "html": html_content,
                    "subject": f"Hempitecture Weekly: {datetime.date.today()}"
                }
            }
        }
    }
    requests.patch(patch_url, json=patch_payload, headers=headers)
    return resp

def post_to_chat(message):
    creds_dict = json.loads(os.environ['GCHAT_CREDS'])
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    chat = build('chat', 'v1', credentials=creds)
    
    space_id = os.environ['GCHAT_SPACE']
    if not space_id.startswith('spaces/'):
        space_id = f"spaces/{space_id}"
        
    body = {'text': message}
    chat.spaces().messages().create(parent=space_id, body=body).execute()

if __name__ == "__main__":
    print("🚀 Starting Hempitecture Newsletter Build...")
    ideas = get_chat_ideas()
    
    if ideas:
        print("💡 Ideas found. Drafting...")
        content = generate_newsletter_html(ideas)
        klaviyo_data = create_klaviyo_draft(content)
        
        if 'data' in klaviyo_data:
            post_to_chat("✅ Thursday Draft is ready in Klaviyo! Content has been injected.")
            print("Done!")
        else:
            print(f"❌ Klaviyo Error: {klaviyo_data}")
    else:
        print("🤷 No #news found this week.")