# The WhatsApp line

Text Nyx from your phone; let Nyx text you. Code: `whatsapp_link.py` (engine side), `whatsapp_worker/worker.py`
(the helper process), `routes_whatsapp.py`, `panels/connectors/WhatsAppLine.tsx`. Tests: `tests/test_whatsapp_link.py`.

## Setting it up

1. **Connectors → Text Nyx from your phone → Set Up WhatsApp.** Installs `neonize` (a Python wrapper around the Go
   WhatsApp library whatsmeow) into Nyx's own Python, about 7 MB.
2. **Your number** with the country code, and **which WhatsApp Nyx uses**:
   - *My own WhatsApp* — you talk to Nyx in your "Message yourself" chat.
   - *A separate number for Nyx* — a spare SIM or eSIM with WhatsApp; you text it like a contact.
3. **Pair My Phone.** Nyx shows a code. On the phone, tap WhatsApp's "Enter code to link new device" notification and
   confirm it (or WhatsApp → Settings → Linked devices → Link a device → Link with phone number instead).

Nyx then texts "Linked to <PC name>". `/help`, `/new`, `/status` and `/pause` work from the phone.

## Why it is built this way

| Decision | Reason |
|---|---|
| Linked device, not the WhatsApp Business Cloud API | The Cloud API needs a Meta business account and a public webhook (a tunnel to this PC). Linking needs nothing but the phone, and the PC only connects outward. |
| Phone-number pairing code instead of a QR code | The owner asked for "put in their phone … all I have to do is confirm". |
| Tied to the PC by a hash of MachineGuid + MAC | The owner asked for "something unique to the PC". A data folder copied elsewhere refuses to start the line. The MAC and GUID are never stored, only the hash. |
| A helper process | The client loads a native DLL; a crash there costs the phone line, not the engine. |
| The helper filters before forwarding | With your own WhatsApp linked it could see every chat. Only the one conversation reaches the engine; other people's messages are never logged or shown to a model. |
| Sends only to the owner's number | There is no recipient field. Nyx cannot message anyone else from here. |
| Phone access "chat" by default | A phone is easier to lose than a PC: answers, web, memory and pictures, not files, apps, shell, orders or settings. "Full" is a switch in the card. |

## Known limits

- WhatsApp's multi-device protocol is used through an **unofficial client**. WhatsApp can restrict numbers that use
  unofficial clients; the separate-number option exists for that reason.
- The line works while Nyx's engine is running and the PC is online. Media (voice notes, pictures) is not handled yet;
  only text.
- Files: `whatsapp/link.json` (who, which PC, recent messages), `whatsapp/session.sqlite3` (the device keys),
  `whatsapp/helper.log`. All git-ignored and kept out of the release zip.
