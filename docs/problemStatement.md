# Voice Agent: Advisor Appointment Scheduler

## Project overview

**Voice Agent: Advisor Appointment Scheduler** is a compliant, pre-booking voice assistant that helps users quickly secure a tentative slot with a human advisor. It collects the consultation topic and preferred time, offers available slots, confirms the booking, and generates a unique booking code. The agent then creates a calendar hold, updates internal notes, and drafts an approval-gated email using MCP. No personal data is taken on the call, clear disclaimers are enforced, and users receive a secure link to complete details later.

This milestone tests practical voice UX, safe intent handling, and real-world AI system orchestration rather than just conversation quality.

---

## Milestone brief

Create a voice agent that books a tentative advisor slot:

1. Collects topic + time preference
2. Offers two slots
3. Confirms the booking
4. Creates a calendar hold, notes entry, and email draft via MCP

The caller gets a **booking code** and a **secure link** to finish details.

---

## Who this helps

- **Users** who want a human consult
- **PMs / Support** running compliant pre-booking

---

## What you must build

### Intents (5)

1. Book new
2. Reschedule
3. Cancel
4. “What to prepare”
5. Check availability windows

### Flow

1. **Greet**
2. **Disclaimer** — “informational, not investment advice”
3. **Confirm topic** (one of):
   - KYC / Onboarding
   - SIP / Mandates
   - Statements / Tax Docs
   - Withdrawals & Timelines
   - Account Changes / Nominee
4. **Collect** day/time preference
5. **Offer** two slots (mock calendar)
6. **On confirm:**
   - Generate Booking Code (e.g., `NL-A742`)
   - **MCP Calendar:** create tentative hold  
     `Advisor Q&A — {Topic} — {Code}`
   - **MCP Notes/Doc:** append `{date, topic, slot, code}` to “Advisor Pre-Bookings”
   - **MCP Email Draft:** prepare advisor email with details (approval-gated)
7. **Read** the booking code + give a secure URL for contact details (outside the call)

---

## Key constraints

- No PII on the call (no phone / email / account numbers)
- State time zone (**IST**) and repeat date/time on confirm
- If no slots match → create waitlist hold + draft email
- Refuse investment advice; provide educational links if asked

---

## What to submit (deliverables)

| Deliverable | Description |
|---|---|
| Working voice demo | Live link **or** ≤3-min call recording |
| Calendar hold | Screenshot with title including booking code |
| Notes + email | Notes/Doc entry + email draft screenshot/text |
| Script file | Short prompts/utterances used |
| README | Mock calendar JSON; how reschedule/cancel works |
