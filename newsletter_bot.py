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
            text_run = el.get('textRun')
            if text_run:
                content = text_run.get('content', '')
                # Check if this specific text has a hyperlink
                link = text_run.get('textStyle', {}).get('link', {}).get('url')
                if link:
                    # Format it so Gemini knows it's a link (Markdown style)
                    text += f"[{content.strip()}]({link}) "
                else:
                    text += content
    return text.strip()

# ── 2. Draft email with Gemini ───────────────────────────────────────────────

def generate_newsletter_html(raw_ideas):
    client = genai.Client(api_key=os.environ['GEMINI_KEY'])
    prompt = f"""You are the brand voice for Hempitecture, a hemp fiber insulation manufacturer based in Jerome, Idaho.
Tone: Innovative, grounded, expert yet accessible. We speak to architects, builders, and sustainability-minded homeowners. Not corporate. Not fluffy.

Task: Synthesize the team notes below into a structured JSON object with three keys corresponding to our newsletter sections.

Rules:
- Output ONLY valid JSON. No markdown formatting blocks around the JSON.
- The three keys must be exactly: "build_section", "impact_section", and "team_section".
- The value for each key should be HTML formatted text (use <p> for body, <strong> for emphasis).
- Do NOT include <h2> headers (these are already in our design template).
- Keep each section to 2-3 sentences max.
- CRITICAL: If the team notes contain a link like [Link Text](URL), you MUST convert it into a standard HTML hyperlink in your output: <a href="URL" style="color: #4A773C; font-weight: bold;">Link Text</a>.

Team notes:
{raw_ideas}"""

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    
    # Parse the JSON string returned by Gemini into a Python dictionary
    return json.loads(response.text)

# ── 3. Create Klaviyo draft ──────────────────────────────────────────────────

def create_klaviyo_draft(html_content_dict):
    headers = {
        "Authorization": f"Klaviyo-API-Key {os.environ['KLAVIYO_KEY']}",
        "revision": "2024-02-15",
        "accept": "application/json",
        "content-type": "application/json"
    }
    subject = f"Hempitecture Weekly: {datetime.date.today().strftime('%B %d')}"

    # Fetch your existing branded template
    base_template_id = os.environ['KLAVIYO_TEMPLATE_ID']
    print(f"Fetching base template: {base_template_id}")
    
    base_resp = requests.get(
        f"https://a.klaviyo.com/api/templates/{base_template_id}/",
        headers=headers
    )
    if base_resp.status_code != 200:
        print(f"Failed to fetch base template: {base_resp.status_code} {base_resp.text}")
        return None
        
    base_html = base_resp.json()['data']['attributes']['html']

    # Inject the Gemini HTML into the specific section placeholders
    merged_html = base_html.replace("[GEMINI_BUILD]", html_content_dict.get("build_section", ""))
    merged_html = merged_html.replace("[GEMINI_IMPACT]", html_content_dict.get("impact_section", ""))
    merged_html = merged_html.replace("[GEMINI_TEAM]", html_content_dict.get("team_section", ""))

    # Step A: Create a new draft template with the merged HTML
    template_resp = requests.post(
        "https://a.klaviyo.com/api/templates/",
        headers=headers,
        json={
            "data": {
                "type": "template",
                "attributes": {
                    "name": f"Newsletter Draft {datetime.date.today()}",
                    "editor_type": "CODE",
                    "html": merged_html
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
        
        # Now html_content_dict is a Python dictionary (from JSON), not a single string!
        html_content_dict = generate_newsletter_html(ideas)
        
        print("Creating Klaviyo draft...")
        campaign_id = create_klaviyo_draft(html_content_dict)
        if campaign_id:
            print(f"Done. Review at: https://www.klaviyo.com/campaigns/{campaign_id}/edit")
        else:
            print("Failed - check logs above.")
    except Exception as e:
        print(f"Error: {e}")
        raise
