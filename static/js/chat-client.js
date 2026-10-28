// Client for the couple's private chat (chat.consumers.ChatConsumer). The
// server holds the messages; this keeps the list the page shows, the
// unread count for the badge, and messages still being sent. Reconnecting
// and the offline queue come from socket-client.js; the server sends the
// latest messages again on every (re)connection.
(function (root) {
  const socketModule =
    typeof module === "object" && module.exports ? require("./socket-client.js") : root;

  function defaultRequestId() {
    if (root.crypto && root.crypto.randomUUID) return root.crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  const TYPING_EVERY_MS = 3000; // Send "typing" at most this often.
  const TYPING_SHOWN_MS = 5000; // Show the partner as typing this long.

  function createChatClient({
    url,
    onChange = () => {},
    newRequestId = defaultRequestId,
    // Where this page is, for the partner's presence line: "space",
    // "menu" or "play:<mode>". Sent on every (re)connection.
    where = null,
    now = () => Date.now(),
    ...socketOptions
  }) {
    let messages = []; // From the server, sorted by id.
    let pending = []; // { requestId, text, failed }, shown after messages.
    let hasMore = false;
    let unread = 0;
    let lastRead = null;
    let partner = "";
    let open = false;
    let closed = false;
    let error = null;
    let connected = false;
    // Your reaction taps not yet confirmed: message id -> { emoji, requestId }.
    // Shown straight away; the server's copy confirms, an error undoes.
    const pendingReactions = new Map();
    let presence = { online: false, where: null, lastSeen: null };
    let partnerTypingUntil = 0;
    let lastTypingSent = -Infinity;
    const schedule = socketOptions.schedule || ((fn, ms) => setTimeout(fn, ms));

    const socket = socketModule.createSocketClient({
      url,
      ...socketOptions,
      onMessage: handle,
      onOpen() {
        if (where) socket.send({ type: "presence", where });
      },
      onGiveUp() {
        connected = false;
        error = "Chat is unavailable right now. Reload the page to try again.";
        onChange();
      },
    });

    function newest() {
      return messages.length ? messages[messages.length - 1].id : null;
    }

    function upsert(list) {
      const byId = new Map(messages.map((m) => [m.id, m]));
      for (const m of list) byId.set(m.id, m);
      messages = [...byId.values()].sort((a, b) => a.id - b.id);
    }

    function isUnread(m) {
      return !m.mine && (lastRead === null || m.id > lastRead);
    }

    function markRead() {
      const upTo = newest();
      unread = 0;
      if (upTo !== null && (lastRead === null || upTo > lastRead)) {
        lastRead = upTo;
        socket.send({ type: "read", upTo });
      }
    }

    function handle(data) {
      if (!data || typeof data !== "object") return;
      if (data.type === "history" && Array.isArray(data.messages)) {
        if (data.initial) {
          // The latest page after a (re)connect: anything in its range that
          // isn't in it was deleted meanwhile; older pages stay.
          const first = data.messages.length ? data.messages[0].id : Infinity;
          messages = messages.filter((m) => m.id < first);
          if (!data.messages.length) messages = [];
          hasMore = Boolean(data.has_more);
          lastRead = data.lastRead ?? null;
          unread = data.unread || 0;
          partner = data.partner || "";
          connected = true;
          upsert(data.messages);
          if (open) markRead();
        } else {
          if (!data.has_more) hasMore = false;
          upsert(data.messages);
        }
      } else if (data.type === "presence" && data.partner) {
        presence = { online: Boolean(data.partner.online), where: data.partner.where ?? null,
                     lastSeen: data.partner.lastSeen ?? null };
      } else if (data.type === "typing") {
        partnerTypingUntil = now() + TYPING_SHOWN_MS;
        schedule(() => onChange(), TYPING_SHOWN_MS + 50);
      } else if (data.type === "message" && data.message) {
        const m = data.message;
        if (!m.mine) partnerTypingUntil = 0;
        const tapped = pendingReactions.get(m.id);
        if (tapped && m.reactions && m.reactions.mine === tapped.emoji) pendingReactions.delete(m.id);
        const known = messages.some((x) => x.id === m.id);
        if (m.requestId) pending = pending.filter((p) => p.requestId !== m.requestId);
        upsert([m]);
        if (!known && isUnread(m)) {
          if (open) markRead();
          else unread++;
        }
      } else if (data.type === "deleted") {
        pendingReactions.delete(data.id);
        const gone = messages.find((m) => m.id === data.id);
        messages = messages.filter((m) => m.id !== data.id);
        if (gone && isUnread(gone) && unread > 0) unread--;
      } else if (data.type === "read" && Number.isInteger(data.upTo)) {
        if (lastRead === null || data.upTo > lastRead) lastRead = data.upTo;
        unread = messages.filter(isUnread).length;
      } else if (data.type === "error") {
        const refused = [...pendingReactions].find(([, tap]) => tap.requestId === data.requestId);
        if (refused) {
          // Only the latest tap per message is tracked, so an older one's
          // error can't undo a newer reaction.
          pendingReactions.delete(refused[0]);
          error = `Couldn't react: ${data.detail || "please try again."}`;
          onChange();
          return;
        }
        if (data.reason === "forbidden") {
          closed = true;
        } else {
          const failed = pending.find((p) => p.requestId === data.requestId);
          if (failed) failed.failed = true;
        }
        error = data.detail || "Something went wrong.";
      } else {
        return;
      }
      onChange();
    }

    function send(text) {
      const trimmed = typeof text === "string" ? text.trim() : "";
      if (!trimmed || closed) return false;
      const requestId = newRequestId();
      pending.push({ requestId, text: trimmed, failed: false });
      error = null;
      socket.send({ type: "send", text: trimmed, requestId });
      onChange();
      return true;
    }

    function typing() {
      if (closed || now() - lastTypingSent < TYPING_EVERY_MS) return;
      lastTypingSent = now();
      socket.send({ type: "typing" });
    }

    function react(id, emoji) {
      const requestId = newRequestId();
      pendingReactions.set(id, { emoji, requestId });
      error = null;
      socket.send({ type: "react", id, emoji, requestId });
      onChange();
    }

    function remove(id) {
      socket.send({ type: "delete", id });
    }

    function loadOlder() {
      if (hasMore && messages.length) socket.send({ type: "history", before: messages[0].id });
    }

    function setOpen(value) {
      open = Boolean(value);
      if (open) markRead();
      onChange();
    }

    function disconnect() {
      connected = false;
      socket.close();
    }

    return {
      connect: () => socket.connect(),
      disconnect,
      send,
      typing,
      react,
      remove,
      loadOlder,
      setOpen,
      get state() {
        return {
          items: [
            ...messages.map((m) => {
              const tapped = pendingReactions.get(m.id);
              const reactions = tapped
                ? { ...(m.reactions || { mine: null, partner: null }), mine: tapped.emoji }
                : m.reactions;
              return { ...m, reactions, pending: false, failed: false };
            }),
            ...pending.map((p) => ({ id: null, text: p.text, mine: true, pending: true, failed: p.failed })),
          ],
          hasMore,
          unread,
          partner,
          open,
          closed,
          connected,
          error,
          presence: { ...presence },
          partnerTyping: now() < partnerTypingUntil,
        };
      },
    };
  }

  if (typeof module === "object" && module.exports) {
    module.exports = { createChatClient };
  } else {
    root.createChatClient = createChatClient;
  }
})(typeof self !== "undefined" ? self : this);
