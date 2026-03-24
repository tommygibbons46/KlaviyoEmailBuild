import os, json, datetime
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests

# 1. Fetch Google Chat Messages (Last 7 Days)
def get_chat_ideas():
    creds_dict = json.loads(os.environ['GCHAT_CREDS'])
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    chat = build('chat', 'v1', credentials=creds)
    
    # List messages from the space
    result = chat.spaces().messages().list(parent=os.environ['GCHAT_SPACE']).execute()
    messages = result.get('messages', [])
    
    # Filter for messages with #news or ideas from the last week
    week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
    raw_text = [m['text'] for m in messages if "#news" in m.get('text', '').lower()]
    return "\n".join(raw_text)

# 2. Synthesize with Gemini
def generate_newsletter_html(raw_ideas):
    genai.configure(api_key=os.environ['GEMINI_KEY'])
    model = genai.GenerativeModel('gemini-1.5-pro')
    
    # This prompt anchors the AI in Hempitecture's specific brand identity
    prompt = f"""
    Context: You are the brand voice for Hempitecture, a leader in sustainable building materials like HempWool.
    Tone: Innovative, grounded, expert yet accessible, and deeply committed to decarbonizing the built environment.
    
    Task: Review these raw team notes from our Google Chat and synthesize them into a 3-section email draft.
    
    Raw Notes: {raw_ideas}
    
    Structure:
    1. 'The Build' (Focus on a specific project or product update)
    2. 'Carbon Impact' (A quick sustainability stat or industry insight)
    3. 'Team News' (Events, milestones, or company updates)
    
    Formatting: Use clean, professional HTML. Avoid corporate jargon; use terms like 'healthy home,' 'thermal performance,' and 'low-embodied carbon.' 
    Output: Return ONLY the raw HTML for the email body.
    """
    response = model.generate_content(prompt)
    return response.text

# 3. Create Klaviyo Draft
def create_klaviyo_draft(html_content):
    url = "https://a.klaviyo.com/api/campaigns/"
    headers = {
        "Authorization": f"Klaviyo-API-Key {os.environ['KLAVIYO_KEY']}",
        "revision": "2024-02-15",
        "accept": "application/json"
    }
    payload = {
        "data": {
            "type": "campaign",
            "attributes": {
                "name": f"Weekly Draft: {datetime.date.today()}",
                "audiences": {"included": [os.environ['KLAVIYO_LIST']]},
                "campaign_type": "email"
                "template_id": "V5BEw8"
            }
        }
    }
    # Note: In production, you'd then use the Campaign ID 
    # to update the 'message' content with the html_content.
    response = requests.post(url, json=payload, headers=headers)
    return response.json()
def send_team_preview(campaign_id):
    """Sends a test email of the newly created draft to the team."""
    # Convert your secret string back into a list
    team_emails = json.loads(os.environ['TEAM_REVIEW_EMAILS'])
    
    url = f"https://a.klaviyo.com/api/campaign-messages/{campaign_id}/test-send/"
    
    headers = {
        "Authorization": f"Klaviyo-API-Key {os.environ['KLAVIYO_KEY']}",
        "revision": "2024-02-15",
        "accept": "application/json",
        "content-type": "application/json"
    }
    
    payload = {
        "data": {
            "type": "campaign-message-test-run",
            "attributes": {
                "emails": team_emails
            }
        }
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.status_code

if __name__ == "__main__":
    ideas = get_chat_ideas()
    if ideas:
        content = generate_newsletter_html(ideas)
        create_klaviyo_draft(content)
        print("Draft created successfully!")