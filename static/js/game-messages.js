// The WebSocket message contract shared with game/consumers.py. Every message
// is an object with a "type" and the sending page's "userId".
//   question       {question: text}                   partner pressed Next
//   reset          {seed: int}                        partner pressed Reset
//   sync_request   {}                                 a page (re)connected
//   sync_response  {seed: int|null, currentQuestion: text|null}
(function (root) {
  const MAX_USER_ID_CHARS = 64;
  const MAX_QUESTION_CHARS = 500;

  const isText = (value, max) =>
    typeof value === "string" && value.length > 0 && value.length <= max;
  const isSeed = (value) => Number.isInteger(value);

  const question = (userId, text) => ({ type: "question", userId, question: text });
  const reset = (userId, seed) => ({ type: "reset", userId, seed });
  const syncRequest = (userId) => ({ type: "sync_request", userId });
  const syncResponse = (userId, seed, currentQuestion) => ({
    type: "sync_response",
    userId,
    seed: isSeed(seed) ? seed : null,
    currentQuestion: currentQuestion || null,
  });

  // Returns the partner's message rebuilt from its allowed fields, or null
  // for anything malformed, unknown, or sent by this page itself.
  function parse(data, myUserId) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const { type, userId } = data;
    if (!isText(userId, MAX_USER_ID_CHARS) || userId === myUserId) return null;

    if (type === "question" && isText(data.question, MAX_QUESTION_CHARS)) {
      return question(userId, data.question);
    }
    if (type === "reset" && isSeed(data.seed)) {
      return reset(userId, data.seed);
    }
    if (type === "sync_request") {
      return syncRequest(userId);
    }
    if (
      type === "sync_response" &&
      (data.seed === null || isSeed(data.seed)) &&
      (data.currentQuestion === null || isText(data.currentQuestion, MAX_QUESTION_CHARS))
    ) {
      return syncResponse(userId, data.seed, data.currentQuestion);
    }
    return null;
  }

  const api = { question, reset, syncRequest, syncResponse, parse };
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.GameMessages = api;
  }
})(typeof self !== "undefined" ? self : this);
