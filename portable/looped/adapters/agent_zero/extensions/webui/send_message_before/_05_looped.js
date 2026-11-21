// Resolve "/looped" in the composer before the message is sent, so the token
// never shows up in the chat. Without an open chat the message is left alone
// and the backend hook handles it.
const PREFIX = /^\s*\/looped(?=\s|$)/i;
const POSTFIX = /\s\/looped\s*$/i;

export default async function loopedCommand(sendCtx) {
  const text = typeof sendCtx?.message === "string" ? sendCtx.message : "";
  if (!PREFIX.test(text) && !POSTFIX.test(text)) return;
  const contextId = sendCtx.context || globalThis.Alpine?.store("chats")?.selected || "";
  if (!contextId) return;

  let result;
  try {
    const { callJsonApi } = await import("/js/api.js");
    result = await callJsonApi("/plugins/looped/mode", {
      context_id: contextId, action: "command", text,
    });
  } catch (error) {
    return; // leave the message unchanged; the backend hook will handle it
  }
  if (!result || !result.ok) return;

  sendCtx.message = result.rest || "";
  if (result.note) {
    try {
      const notify = await import("/components/notifications/notification-store.js");
      void notify.toastFrontendInfo?.(result.note, "Looped Mode");
    } catch (error) { /* a toast is optional */ }
  }
  const hasAttachments = Array.isArray(sendCtx.attachments) && sendCtx.attachments.length > 0;
  if (!sendCtx.message.trim() && !hasAttachments) {
    sendCtx.cancel = true;
    try {
      // Clear the composer, since a cancelled send leaves the command in it.
      const input = await import("/components/chat/input/input-store.js");
      input.store?.reset?.();
    } catch (error) {
      const field = document.getElementById("chat-input");
      if (field && "value" in field) field.value = "";
    }
  }
}
