import os
import json
import datetime
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google import genai

# ── 1. Fetch Google Doc content ──────────────────────────────────────────────

def get_doc_content():
    creds_dict = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_KEY'])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/documents.readonly']
    )
    creds.refresh(Request())
    docs = build('docs', 'v1', credentials=creds)
    doc = docs.documents().get(documentId=os.environ['GOOGLE_DOC_ID']).execute()
    text = ''
    for block in doc.get('body', {}).get('content', []):
        for el in block.get('paragraph', {}).get('elements', []):
            text += el.get('textRun', {}).get('content', '')
    return text.strip()

# ── 2. Draft email with Gemini ───────────────────────────────────────────────

def generate_newsletter_html(raw_ideas):
    client = genai.Client(api_key=os.environ['GEMINI_KEY'])
    prompt = f"""You are the brand voice for Hempitecture, a hemp fiber insulation manufacturer based in Jerome, Idaho.
Tone: Innovative, grounded, expert yet accessible. We speak to architects, builders, and sustainability-minded homeowners. Not corporate. Not fluffy.

Task: Synthesize the team notes below into a newsletter email with these three sections:
1. "The Build" - product news, project highlights, technical updates
2. "Carbon Impact" - sustainability angles, certifications, environmental wins
3. "Team News" - people, culture, company updates

Rules:
- Write in HTML body format only (no html, head, or body tags)
- Use h2 for section headers, p for copy
- Keep each section to 2-3 sentences max
- One clear CTA at the end: a p with a bolded link like <strong><a href="[CTA_URL]">Shop HempWool</a></strong>
- If a section has no relevant notes, write one short bridging sentence
- Do not invent facts

Team notes:
{raw_ideas}

Return ONLY raw HTML. No markdown, no backticks, no explanation."""
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    return response.text

# ── 3. Create Klaviyo draft ──────────────────────────────────────────────────

def create_klaviyo_draft(html_content):
    headers = {
        "Authorization": f"Klaviyo-API-Key {os.environ['KLAVIYO_KEY']}",
        "revision": "2024-02-15",
        "accept": "application/json",
        "content-type": "application/json"
    }
    subject = f"Hempitecture Weekly: {datetime.date.today().strftime('%B %d')}"

    # Step A: Create a new template with the Gemini-generated HTML
    template_resp = requests.post(
        "https://a.klaviyo.com/api/templates/",
        headers=headers,
        json={
            "data": {
                "type": "template",
                "attributes": {
                    "name": f"Newsletter Draft {datetime.date.today()}",
                    "editor_type": "CODE",
                    "html": html_content
                }
            }
        }
    )
    if template_resp.status_code not in (200, 201):
        print(f"Template creation failed: {template_resp.status_code} {template_resp.text}")
        return None
    template_id = template_resp.json()['data']['id']
    print(f"Template created: {template_id}")

    # Step B: Create campaign with message
    resp = requests.post(
        "https://a.klaviyo.com/api/campaigns/",
        headers=headers,
        json={
            "data": {
                "type": "campaign",
                "attributes": {
                    "name": f"Weekly Draft: {datetime.date.today()}",
                    "audiences": {"included": [os.environ['KLAVIYO_LIST']]},
                    "campaign-messages": {
                        "data": [{
                            "type": "campaign-message",
                            "attributes": {
                                "channel": "email",
                                "label": "Email",
                                "content": {
                                    "subject": subject,
                                    "preview_text": "This week from the hemp fields",
                                    "from_email": "hello@hempitecture.com",
                                    "from_label": "Hempitecture",
                                    "reply_to_email": "hello@hempitecture.com"
                                }
                            }
                        }]
                    }
                }
            }
        }
    )
    if resp.status_code not in (200, 201):
        print(f"Campaign creation failed: {resp.status_code} {resp.text}")
        return None
    campaign_id = resp.json()['data']['id']
    print(f"Campaign created: {campaign_id}")

    # Step C: Get the message ID
    msg_resp = requests.get(
        f"https://a.klaviyo.com/api/campaigns/{campaign_id}/campaign-messages/",
        headers=headers
    )
    msg_id = msg_resp.json()['data'][0]['id']
    print(f"Message ID: {msg_id}")

 # Step D: Assign template using the dedicated action endpoint
    assign_resp = requests.post(
        "https://a.klaviyo.com/api/campaign-message-assign-template/",
        headers=headers,
        json={
            "data": {
                "type": "campaign-message",
                "id": msg_id,
                "relationships": {
                    "template": {
                        "data": {
                            "type": "template",
                            "id": template_id
                        }
                    }
                }
            }
        }
    )
    print(f"Template assign status: {assign_resp.status_code}")
    if assign_resp.status_code not in (200, 201, 204):
        print(f"Assign error: {assign_resp.text}")
    return campaign_id

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting Hempitecture newsletter build...")
    try:
        ideas = get_doc_content()
        if not ideas:
            print("Doc is empty - skipping.")
            exit(0)
        print(f"Doc fetched ({len(ideas)} chars). Drafting with Gemini...")
        html = generate_newsletter_html(ideas)
        print("Creating Klaviyo draft...")
        campaign_id = create_klaviyo_draft(html)
        if campaign_id:
            print(f"Done. Review at: https://www.klaviyo.com/campaigns/{campaign_id}/edit")
        else:
            print("Failed - check logs above.")
    except Exception as e:
        print(f"Error: {e}")
        raise
