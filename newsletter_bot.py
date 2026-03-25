import os, json, datetime, requests
from google import genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# ── 1. Fetch content from shared Google Doc ──────────────────────────────────

def get_doc_content():
    creds_dict = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_KEY'])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/documents.readonly']
    )
    creds.refresh(Request())  # force token refresh, same pattern you already had
    
    docs = build('docs', 'v1', credentials=creds)
    doc = docs.documents().get(documentId=os.environ['GOOGLE_DOC_ID']).execute()

    text = ''
    for block in doc.get('body', {}).get('content', []):
        for el in block.get('paragraph', {}).get('elements', []):
            text += el.get('textRun', {}).get('content', '')
    
    content = text.strip()
    if not content:
        print("Doc is empty — nothing to draft.")
    return content

# ── 2. Draft email copy with Gemini ─────────────────────────────────────────



# ── 3. Create Klaviyo campaign draft ─────────────────────────────────────────
# Replace generate_newsletter_html with:
def generate_newsletter_html(raw_ideas):
    client = genai.Client(api_key=os.environ['GEMINI_KEY'])
    
    prompt = f"""
You are the brand voice for Hempitecture, a hemp fiber insulation manufacturer based in Jerome, Idaho.
Tone: Innovative, grounded, expert yet accessible. We speak to architects, builders, and sustainability-minded homeowners. Not corporate. Not fluffy.

Task: Synthesize the team's notes below into a newsletter email with these three sections:
1. "The Build" — product news, project highlights, technical updates
2. "Carbon Impact" — sustainability angles, certifications, environmental wins  
3. "Team News" — people, culture, company updates

Rules:
- Write in HTML body format only (no <html>, <head>, or <body> tags)
- Use <h2> for section headers, <p> for copy
- Keep each section to 2-3 sentences max
- One clear CTA at the end: a <p> with <strong><a href="[CTA_URL]">Shop HempWool →</a></strong>
- If a section has no relevant notes, write one short bridging sentence rather than skipping it
- Do not invent facts — only use what's in the notes

Team notes this week:
{raw_ideas}

Return ONLY the raw HTML. No markdown, no backticks, no explanation.
"""
    response = client.models.generate_content(
        model='gemini-1.5-pro',
        contents=prompt
    )
    return response.text
def create_klaviyo_draft(html_content):
    headers = {
        "Authorization": f"Klaviyo-API-Key {os.environ['KLAVIYO_KEY']}",
        "revision": "2024-02-15",
        "accept": "application/json",
        "content-type": "application/json"
    }
    subject = f"Hempitecture Weekly: {datetime.date.today().strftime('%B %d')}"

    # Step A: Create campaign shell
    # NOTE: template_id and campaign_type are NOT valid here in the 2024 API —
    # template goes on the message definition, not the campaign
    campaign_payload = {
        "data": {
            "type": "campaign",
            "attributes": {
                "name": f"Weekly Draft: {datetime.date.today()}",
                "audiences": {"included": [os.environ['KLAVIYO_LIST']]},
                "send_strategy": {"method": "static"},
                "campaign_messages": {
                    "data": [{
                        "type": "campaign-message",
                        "attributes": {
                            "channel": "email",
                            "label": "Email",
                            "content": {
                                "subject": subject,
                                "preview_text": "This week from the hemp fields →",
                                "from_email": "hello@hempitecture.com",
                                "from_label": "Hempitecture",
                                "reply_to_email": "hello@hempitecture.com",
                            },
                            "definition": {
                                "template": {
                                    "type": "template",
                                    "id": os.environ['KLAVIYO_TEMPLATE_ID']
                                }
                            }
                        }
                    }]
                }
            }
        }
    }

    resp = requests.post(
        "https://a.klaviyo.com/api/campaigns/",
        json=campaign_payload,
        headers=headers
    )

    if resp.status_code not in (200, 201):
        print(f"Klaviyo campaign creation failed: {resp.status_code} {resp.text}")
        return None

    campaign_id = resp.json()['data']['id']
    print(f"Campaign created: {campaign_id}")

    # Step B: Get the auto-created message ID, then PATCH in the HTML
    msg_resp = requests.get(
        f"https://a.klaviyo.com/api/campaigns/{campaign_id}/campaign-messages/",
        headers=headers
    )
    msg_id = msg_resp.json()['data'][0]['id']

    patch_resp = requests.patch(
        f"https://a.klaviyo.com/api/campaign-messages/{msg_id}/",
        headers=headers,
        json={
            "data": {
                "type": "campaign-message",
                "id": msg_id,
                "attributes": {
                    "content": {
                        "html": html_content,
                        "subject": subject
                    }
                }
            }
        }
    )
    print(f"Content patch status: {patch_resp.status_code}")
    return campaign_id

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting Hempitecture newsletter build...")
    try:
        ideas = get_doc_content()
        if not ideas:
            print("No content in doc — skipping.")
            exit(0)

        print(f"Doc fetched ({len(ideas)} chars). Drafting with Gemini...")
        html = generate_newsletter_html(ideas)

        print("Creating Klaviyo draft...")
        campaign_id = create_klaviyo_draft(html)

        if campaign_id:
            print(f"Done. Review at: https://www.klaviyo.com/campaigns/{campaign_id}/edit")
        else:
            print("Failed — check logs above.")

    except Exception as e:
        print(f"Error: {e}")
        raise
