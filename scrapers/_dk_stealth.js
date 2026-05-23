// Comprehensive stealth init script for DraftKings Akamai bypass.
//
// Patches the well-known headless-Chrome tells that Akamai's sensor data
// script checks. Ported from puppeteer-extra-plugin-stealth evasions:
//   https://github.com/berstend/puppeteer-extra/tree/master/packages/puppeteer-extra-plugin-stealth/evasions
//
// Run via page.add_init_script() so it executes before any page script.

(() => {
  // ─── 1. navigator.webdriver ─────────────────────────────────────────────
  // The most basic tell. delete and redefine.
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (e) {}

  // ─── 2. window.chrome stub ──────────────────────────────────────────────
  // Real Chrome has window.chrome.{app, csi, loadTimes, runtime}. Headless
  // Chrome only has runtime in some versions, none in others.
  if (!window.chrome) {
    window.chrome = {};
  }
  if (!window.chrome.runtime) {
    window.chrome.runtime = {
      OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
      OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
      PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
      PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
      PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
      RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' },
    };
  }
  if (!window.chrome.loadTimes) {
    window.chrome.loadTimes = function () {
      return {
        commitLoadTime: Date.now() / 1000 - Math.random() * 5,
        connectionInfo: 'h2',
        finishDocumentLoadTime: Date.now() / 1000 - Math.random() * 4,
        finishLoadTime: Date.now() / 1000 - Math.random() * 3,
        firstPaintAfterLoadTime: 0,
        firstPaintTime: Date.now() / 1000 - Math.random() * 4,
        navigationType: 'Other',
        npnNegotiatedProtocol: 'h2',
        requestTime: Date.now() / 1000 - Math.random() * 6,
        startLoadTime: Date.now() / 1000 - Math.random() * 6,
        wasAlternateProtocolAvailable: false,
        wasFetchedViaSpdy: true,
        wasNpnNegotiated: true,
      };
    };
  }
  if (!window.chrome.csi) {
    window.chrome.csi = function () {
      return {
        onloadT: Date.now(),
        pageT: Date.now() - performance.timing.navigationStart,
        startE: performance.timing.navigationStart,
        tran: 15,
      };
    };
  }
  if (!window.chrome.app) {
    window.chrome.app = {
      InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
      RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
      getDetails: function () { return null; },
      getIsInstalled: function () { return false; },
      isInstalled: false,
    };
  }

  // ─── 3. navigator.plugins / mimeTypes ──────────────────────────────────
  // Headless Chrome reports an empty plugins array. Real Chrome has 5.
  try {
    const fakePlugins = [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    ];
    Object.defineProperty(navigator, 'plugins', {
      get: () => {
        const arr = [...fakePlugins];
        arr.item = (i) => arr[i] || null;
        arr.namedItem = (n) => arr.find((p) => p.name === n) || null;
        arr.refresh = () => {};
        return arr;
      },
    });
    Object.defineProperty(navigator, 'mimeTypes', {
      get: () => {
        const m = [{ type: 'application/pdf', suffixes: 'pdf', description: '', enabledPlugin: fakePlugins[0] }];
        m.item = (i) => m[i] || null;
        m.namedItem = (n) => m.find((x) => x.type === n) || null;
        return m;
      },
    });
  } catch (e) {}

  // ─── 4. navigator.languages ────────────────────────────────────────────
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  } catch (e) {}

  // ─── 5. navigator.vendor ───────────────────────────────────────────────
  try {
    Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
  } catch (e) {}

  // ─── 6. navigator.hardwareConcurrency ──────────────────────────────────
  // Plausible value (random of common counts). DC instances often expose 2.
  try {
    const cores = [4, 8, 8, 8, 16][Math.floor(Math.random() * 5)];
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => cores });
  } catch (e) {}

  // ─── 7. navigator.deviceMemory ─────────────────────────────────────────
  try {
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
  } catch (e) {}

  // ─── 8. navigator.permissions.query — Notification.permission fix ──────
  try {
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
      window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : origQuery(parameters);
    }
  } catch (e) {}

  // ─── 9. WebGL vendor / renderer ─────────────────────────────────────────
  // Headless reports "Google SwANGLE" or "Mesa". Real Chrome on macOS reports
  // "Google Inc. (Apple)" / "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, ...)"
  try {
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (param) {
      // UNMASKED_VENDOR_WEBGL
      if (param === 37445) return 'Google Inc. (Apple)';
      // UNMASKED_RENDERER_WEBGL
      if (param === 37446) return 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)';
      return getParam.call(this, param);
    };
    if (window.WebGL2RenderingContext) {
      const getParam2 = WebGL2RenderingContext.prototype.getParameter;
      WebGL2RenderingContext.prototype.getParameter = function (param) {
        if (param === 37445) return 'Google Inc. (Apple)';
        if (param === 37446) return 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)';
        return getParam2.call(this, param);
      };
    }
  } catch (e) {}

  // ─── 10. iframe.contentWindow Proxy ────────────────────────────────────
  // Akamai sometimes injects an iframe and tests its contentWindow for
  // bot-tells. Patch it to return the same fake chrome stub.
  try {
    const origIframe = HTMLIFrameElement.prototype;
    Object.defineProperty(origIframe, 'contentWindow', {
      get: function () {
        const cw = this.contentDocument ? this.contentDocument.defaultView : null;
        if (cw && !cw.chrome) cw.chrome = window.chrome;
        return cw;
      },
    });
  } catch (e) {}

  // ─── 11. Remove HeadlessChrome from userAgent (belt-and-suspenders) ────
  // The launch flag --disable-blink-features=AutomationControlled mostly
  // handles this, but verify.
  try {
    if (navigator.userAgent.includes('HeadlessChrome')) {
      Object.defineProperty(navigator, 'userAgent', {
        get: () =>
          navigator.userAgent.replace('HeadlessChrome', 'Chrome'),
      });
    }
  } catch (e) {}

  // ─── 12. window.outerHeight/Width must equal innerHeight/Width ─────────
  // Akamai checks that these are reasonably close (real users have window
  // chrome). We set them equal to viewport which matches some browsers.
  try {
    const ih = window.innerHeight;
    const iw = window.innerWidth;
    Object.defineProperty(window, 'outerHeight', { get: () => ih + 87 }); // toolbar
    Object.defineProperty(window, 'outerWidth', { get: () => iw });
  } catch (e) {}

  // ─── 13. Function.prototype.toString — make patched fns look native ────
  try {
    const nativeToString = Function.prototype.toString;
    Function.prototype.toString = function () {
      if (this === Function.prototype.toString) return nativeToString.call(this);
      // Functions we have patched should still print as "native code"
      const name = this.name || '';
      if (['get', 'getParameter', 'query', 'loadTimes', 'csi'].some((x) => name.includes(x))) {
        return `function ${name}() { [native code] }`;
      }
      return nativeToString.call(this);
    };
  } catch (e) {}
})();
