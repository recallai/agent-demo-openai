# Working on this sample

Keep this a small OpenAI Realtime and Recall meeting agent demo. The local launcher
has one meeting-URL input. Use native Recall OpenAI audio and a server-side
Realtime connection for tools; webpage sharing is the visual output.
Do not add a speaking avatar or an avatar-provider dependency.

- Launch `web_4_core` bots on Zoom, Google Meet, Microsoft Teams, and Webex.
- Nine tools: start_screenshare, send_chat_message, send_current_page_link,
  stop_screenshare, leave_call, mute_agent, unmute_agent, stop_listening,
  start_listening.
- Admit requests beginning with Assistant or openai demo before generating a
  response. Other conversation must not interrupt responses or enter their input.
- Join silently. Post one short introduction where meeting chat is available.
  Answer naturally with enough detail to be useful, without unsolicited advice
  or repeated offers.
- Mute controls speech only; requested tools remain available. Stop listening
  separately ignores requests except a standalone addressed start-listening
  command. Preserve mute across listening changes and never replay skipped turns.
- Every accepted tool provides feedback where chat is available. Requested
  messages and links are their own confirmation. Feedback failure must not retry
  or undo an action.
- Sharing displays a public HTTPS URL; it does not read or control the page.
  Preserve the last accepted URL if a later request fails. Do not post a link
  automatically or claim a page rendered merely because Recall accepted it.
- Keep lifecycle, meeting actions, and HTTP requests easy to trace. Use concrete
  names and cohesive files; review responsibilities near 300 lines.
- Use Recall MCP docs and official OpenAI docs for API behavior. Verify the
  implementation when an integration detail is missing from the docs.
- Keep credentials in the ignored root .env or process environment. Never print
  secrets, commit them, or persist meeting content. Use the Recall API key for
  the workspace and region where the OpenAI key is configured.
- Keep the launcher on localhost. No public webhook receiver or media bridge is
  needed. Only attach to OpenAI calls discovered for bots this process creates.
- Do not add evaluator code, test harnesses, verification instrumentation, or
  reports to this repository. The user performs the live demo; verification and
  local checks happen externally. Report their limits honestly.
