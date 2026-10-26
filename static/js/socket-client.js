// WebSocket wrapper for the play page: reconnects with exponential backoff,
// queues messages while offline (bounded), and parses incoming JSON.
(function (root) {
  const OPEN = 1;

  function createSocketClient({
    url,
    onMessage,
    // Called after every successful (re)connection, once queued messages
    // have been sent.
    onOpen = () => {},
    WebSocketImpl = root.WebSocket,
    schedule = (fn, ms) => setTimeout(fn, ms),
    maxAttempts = 5,
    maxQueue = 50,
  }) {
    let socket = null;
    let attempts = 0;
    let retryPending = false;
    const queue = [];

    function connect() {
      if (socket || retryPending) return;
      socket = new WebSocketImpl(url);
      socket.onopen = () => {
        attempts = 0;
        flush();
        onOpen();
      };
      socket.onmessage = (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch (err) {
          console.warn("Ignoring non-JSON WebSocket message");
          return;
        }
        onMessage(data);
      };
      // An error is always followed by close, so reconnecting happens there.
      socket.onclose = () => {
        socket = null;
        scheduleReconnect();
      };
    }

    function scheduleReconnect() {
      if (attempts >= maxAttempts) return;
      retryPending = true;
      const delay = Math.min(1000 * 2 ** attempts, 10000);
      attempts++;
      schedule(() => {
        retryPending = false;
        connect();
      }, delay);
    }

    function flush() {
      while (queue.length && socket && socket.readyState === OPEN) {
        try {
          socket.send(queue[0]);
        } catch (err) {
          console.warn("Failed to send queued message:", err);
          return;
        }
        queue.shift();
      }
    }

    function send(message) {
      queue.push(JSON.stringify(message));
      if (queue.length > maxQueue) queue.shift();
      if (socket) {
        flush();
      } else if (!retryPending) {
        // We gave up reconnecting earlier; a new action earns a fresh try.
        attempts = 0;
        connect();
      }
    }

    return {
      connect,
      send,
      get queueLength() {
        return queue.length;
      },
      get isOpen() {
        return Boolean(socket) && socket.readyState === OPEN;
      },
    };
  }

  if (typeof module === "object" && module.exports) {
    module.exports = { createSocketClient };
  } else {
    root.createSocketClient = createSocketClient;
  }
})(typeof self !== "undefined" ? self : this);
