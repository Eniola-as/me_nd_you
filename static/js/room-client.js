// Client for server-authoritative game rooms (play.consumers.RoomConsumer).
// The server decides everything; this only sends intents and renders the
// newest state it receives. Reconnecting is handled by socket-client.js, and
// the server sends the current state on every (re)connection.
(function (root) {
  const socketModule =
    typeof module === "object" && module.exports ? require("./socket-client.js") : root;

  function defaultRequestId() {
    if (root.crypto && root.crypto.randomUUID) return root.crypto.randomUUID();
    // Fallback for older browsers: random, not security sensitive.
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function createRoomClient({
    url,
    onState,
    onError = () => {},
    newRequestId = defaultRequestId,
    ...socketOptions
  }) {
    let version = 0;

    const socket = socketModule.createSocketClient({
      url,
      ...socketOptions,
      onMessage(message) {
        if (!message || typeof message !== "object") return;
        if (message.type === "state" && Number.isInteger(message.version)) {
          // Only ever move forward; repeats and late arrivals are ignored.
          if (message.version > version) {
            version = message.version;
            onState(message);
          }
        } else if (message.type === "error") {
          onError(message);
        }
      },
    });

    function act(action, payload) {
      const message = { type: "action", action, expectedVersion: version, requestId: newRequestId() };
      if (payload !== undefined) message.payload = payload;
      socket.send(message);
    }

    return {
      connect: () => socket.connect(),
      act,
      get version() {
        return version;
      },
    };
  }

  if (typeof module === "object" && module.exports) {
    module.exports = { createRoomClient };
  } else {
    root.createRoomClient = createRoomClient;
  }
})(typeof self !== "undefined" ? self : this);
