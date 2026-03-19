const SERVER = "http://localhost:9234/capture";

// Inject into MAIN world when tab loads
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "loading") return;
  if (!tab.url?.includes("shopee.vn")) return;

  chrome.scripting
    .executeScript({
      target: { tabId },
      files: ["injector.js"],
      world: "MAIN",
      injectImmediately: true,
    })
    .catch(() => {});
});

chrome.webNavigation?.onHistoryStateUpdated?.addListener(
  (details) => {
    if (details.frameId !== 0) return;
    chrome.scripting
      .executeScript({
        target: { tabId: details.tabId },
        files: ["injector.js"],
        world: "MAIN",
      })
      .catch(() => {});
  },
  { url: [{ hostContains: "shopee.vn" }] }
);

// Forward captured data to local server, enriched with cookies
chrome.runtime.onMessage.addListener((message) => {
  if (message.action !== "capture") return;

  // Get cookies and attach to the request data
  chrome.cookies.getAll({ domain: ".shopee.vn" }, (cookies) => {
    const cookieStr = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    const enriched = { ...message.data, cookies: cookieStr };

    fetch(SERVER, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(enriched),
    })
      .then(() =>
        console.log("Sent:", message.data.method, message.data.url?.substring(0, 80))
      )
      .catch((e) => console.log("Send failed:", e.message));
  });
});

console.log("Shopee Capture background ready (v2.2)");
