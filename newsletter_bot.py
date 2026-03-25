def create_klaviyo_draft(html_content):
    headers = {
        "Authorization": f"Klaviyo-API-Key {os.environ['KLAVIYO_KEY']}",
        "revision": "2024-02-15",
        "accept": "application/json",
        "content-type": "application/json"
    }
    subject = f"Hempitecture Weekly: {datetime.date.today().strftime('%B %d')}"

    # Step A: Create the campaign shell (no messages here)
    campaign_payload = {
        "data": {
            "type": "campaign",
            "attributes": {
                "name": f"Weekly Draft: {datetime.date.today()}",
                "audiences": {"included": [os.environ['KLAVIYO_LIST']]},
                "send_strategy": {"method": "static"}
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

    # Step B: Create the message on the campaign
    msg_payload = {
        "data": {
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
                }
            },
            "relationships": {
                "campaign": {
                    "data": {"type": "campaign", "id": campaign_id}
                }
            }
        }
    }

    msg_resp = requests.post(
        "https://a.klaviyo.com/api/campaign-messages/",
        json=msg_payload,
        headers=headers
    )

    if msg_resp.status_code not in (200, 201):
        print(f"Message creation failed: {msg_resp.status_code} {msg_resp.text}")
        return None

    msg_id = msg_resp.json()['data']['id']
    print(f"Message created: {msg_id}")

    # Step C: PATCH the HTML content onto the message
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
