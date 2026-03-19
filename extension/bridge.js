// ISOLATED world - forwards MAIN world messages to background
window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (event.data?.type !== "__SHOPEE_CAPTURE__") return;
  try {
    chrome.runtime.sendMessage({ action: "capture", data: event.data.payload });
  } catch (e) {
    // Extension context invalidated after reload - ignore
  }
});
