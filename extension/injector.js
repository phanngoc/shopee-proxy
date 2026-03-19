// Injected into MAIN world via chrome.scripting.executeScript (bypasses CSP)
(function () {
  if (window.__shopeeCapture) return;
  window.__shopeeCapture = true;

  function isApi(url) {
    return url && (url.includes("/api/") || url.includes("/gql"));
  }

  function emit(entry) {
    window.postMessage({ type: "__SHOPEE_CAPTURE__", payload: entry }, "*");
  }

  // Intercept fetch
  const _fetch = window.fetch;
  window.fetch = async function (...args) {
    const [input, init] = args;
    const url = typeof input === "string" ? input : input?.url || "";

    if (!isApi(url)) return _fetch.apply(this, args);

    const method = (init?.method || "GET").toUpperCase();
    let reqBody = null;
    if (init?.body) {
      try {
        reqBody =
          typeof init.body === "string"
            ? init.body
            : JSON.stringify(init.body);
      } catch {
        reqBody = String(init.body);
      }
    }

    const reqHeaders = {};
    if (init?.headers) {
      const h =
        init.headers instanceof Headers
          ? init.headers
          : new Headers(init.headers);
      h.forEach((v, k) => (reqHeaders[k] = v));
    }

    const resp = await _fetch.apply(this, args);
    const clone = resp.clone();
    clone
      .text()
      .then((body) => {
        emit({
          method,
          url,
          timestamp: new Date().toISOString(),
          requestHeaders: reqHeaders,
          requestBody: reqBody,
          responseStatus: resp.status,
          responseBody: body,
        });
      })
      .catch(() => {});

    return resp;
  };

  // Intercept XMLHttpRequest
  const _open = XMLHttpRequest.prototype.open;
  const _send = XMLHttpRequest.prototype.send;
  const _setHeader = XMLHttpRequest.prototype.setRequestHeader;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this._cap = { method: method.toUpperCase(), url, headers: {} };
    return _open.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
    if (this._cap) this._cap.headers[k] = v;
    return _setHeader.call(this, k, v);
  };

  XMLHttpRequest.prototype.send = function (body) {
    if (this._cap && isApi(this._cap.url)) {
      const cap = this._cap;
      cap.requestBody = body;
      cap.timestamp = new Date().toISOString();
      this.addEventListener("load", function () {
        emit({
          method: cap.method,
          url: cap.url,
          timestamp: cap.timestamp,
          requestHeaders: cap.headers,
          requestBody: cap.requestBody,
          responseStatus: this.status,
          responseBody: this.responseText,
        });
      });
    }
    return _send.call(this, body);
  };

  console.log("[Shopee Capture] v2.1 active");
})();
