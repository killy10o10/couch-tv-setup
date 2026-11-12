(function () {
  "use strict";
  var KEY = document.querySelector('meta[name="setup-key"]').content;
  // Show only the help that fits this computer (mac, windows or linux).
  var OS = document.querySelector('meta[name="setup-os"]').content;
  document.querySelectorAll("[data-os]").forEach(function (el) { el.hidden = el.dataset.os !== OS; });
  var STEPS = ["welcome", "adb", "find", "allow", "install", "home", "check", "pair", "personalise", "ads", "done"];
  var $ = function (id) { return document.getElementById(id); };
  var state = { ip: null, device: null, picks: [], place: null, mode: "setup" };

  // ---- talking to the setup program on this computer ----
  function call(path, body) {
    return fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-Setup-Key": KEY },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) { var e = new Error(j.error || "Something went wrong."); e.code = j.code; throw e; }
        return j;
      });
    });
  }
  /** Starts a slow step and follows it until it ends. onProgress(fraction, message). */
  function job(path, body, onProgress) {
    return call(path, body || {}).then(function () {
      return new Promise(function (resolve, reject) {
        (function poll() {
          call("/api/job").then(function (j) {
            if (onProgress) onProgress(j.progress || 0, j.message || "");
            if (j.running) return setTimeout(poll, 400);
            if (j.error) { var e = new Error(j.error); e.code = j.code; reject(e); } else resolve(j.result);
          }, reject);
        })();
      });
    });
  }
  function showError(e) { var el = $("error"); el.textContent = e ? (e.message || String(e)) : ""; el.hidden = !e; }
  // Building the page from parts, never from HTML text: names from the network (a TV's name, an
  // app's name, a place from the weather search) are always shown as plain text.
  function node(x) { return typeof x === "string" ? document.createTextNode(x) : x; }
  function h(tag, cls) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    for (var i = 2; i < arguments.length; i++) e.appendChild(node(arguments[i]));
    return e;
  }
  function put(target) {
    target.textContent = "";
    for (var i = 1; i < arguments.length; i++) target.appendChild(node(arguments[i]));
  }
  function b(text) { return h("b", null, String(text)); }
  function good(text) { return h("span", "good", "✓ " + text); }
  function busy() {
    var f = document.createDocumentFragment();
    f.appendChild(h("span", "spin"));
    for (var i = 0; i < arguments.length; i++) f.appendChild(node(arguments[i]));
    return f;
  }

  // ---- moving between steps ----
  var dots = $("dots");
  STEPS.forEach(function () { dots.appendChild(document.createElement("li")); });
  function go(name) {
    showError(null);
    var at = STEPS.indexOf(name);
    document.querySelectorAll("section").forEach(function (s) { s.classList.toggle("on", s.dataset.step === name); });
    Array.prototype.forEach.call(dots.children, function (d, i) { d.className = i === at ? "on" : i < at ? "past" : ""; });
    var enter = ENTER[name];
    if (enter) enter();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-go]");
    if (b) go(b.dataset.go);
  });

  var ENTER = {};

  // ---- find ----
  ENTER.find = scan;
  function scan() {
    put($("find-status"), busy("Looking on your Wi-Fi…"));
    put($("found"));
    $("find-help").hidden = true;
    call("/api/scan").then(function (r) {
      if (!r.tvs.length) {
        $("find-status").textContent = "No TV found yet.";
        $("find-help").hidden = false;
        $("manual").open = true;
        return;
      }
      $("find-status").textContent = r.tvs.length === 1 ? "Found one. Is this your TV?" : "Found " + r.tvs.length + ". Which is your TV?";
      r.tvs.forEach(function (t, i) {
        var btn = h("button", i === 0 ? "primary" : null, h("span", null, String(t.name || "Fire TV")), h("small", null, String(t.ip)));
        btn.onclick = function () { connect(t.ip); };
        $("found").appendChild(btn);
      });
    }, showError);
  }
  $("rescan").onclick = scan;
  $("ip-go").onclick = function () {
    var ip = $("ip").value.trim();
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) return showError(new Error("That does not look like an address. It is four numbers with dots, like 192.168.1.23."));
    connect(ip);
  };

  // ---- allow ----
  function connect(ip) {
    state.ip = ip;
    go("allow");
    $("allow-retry").hidden = true;
    put($("allow-status"), busy("Tick ", b("Always allow from this computer"), ", then press ", b("Allow"), "."));
    job("/api/connect", { ip: ip }).then(function (dev) {
      state.device = dev;
      if (!dev.supported) {
        put($("allow-status"), "This is a ", b(dev.name), " (" + dev.os + "). This setup is made for Fire TV sticks, so it stops here.");
        return;
      }
      go(state.mode === "undo" ? "undo" : "install");
    }, function (e) {
      $("allow-status").textContent = e.message;
      $("allow-retry").hidden = false;
    });
  }
  $("allow-retry").onclick = function () { connect(state.ip); };

  // ---- install ----
  ENTER.install = function () {
    var d = state.device, app = d.app || {};
    put($("device-line"), "Connected to your ", b(d.name), " (" + d.os + ").");
    $("install-bar").style.width = "0";
    $("install-bar").parentNode.hidden = true;
    $("install-replace").hidden = true;
    $("install-status").textContent = app.installed
      ? "Couch TV " + (app.version || "") + " is already on this TV. Update it to the newest version, or keep it."
      : "This downloads Couch TV (about 35 MB) and puts it on the TV.";
    $("install-title").textContent = app.installed ? "Update Couch TV" : "Install Couch TV";
    $("install-go").textContent = app.installed ? "Update" : "Install";
    $("install-go").disabled = false;
    $("install-skip").hidden = !app.installed;
  };
  function install(replace) {
    $("install-go").disabled = true;
    $("install-replace").hidden = true;
    $("install-skip").hidden = true;
    $("install-bar").parentNode.hidden = false;
    job("/api/install", { replace: !!replace }, function (f, msg) {
      $("install-bar").style.width = Math.round(f * 100) + "%";
      if (msg) put($("install-status"), busy(msg + "…"));
    }).then(function (r) {
      put($("install-status"), good("Couch TV " + r.apk.version + " is on the TV."));
      state.device.app = r.app;
      setTimeout(function () { go("home"); }, 900);
    }, function (e) {
      $("install-go").disabled = false;
      if (e.code === "different_key") {
        $("install-status").textContent = "";
        $("install-replace").hidden = false;
        $("install-skip").hidden = false;
      } else showError(e);
    });
  }
  $("install-go").onclick = function () { install(false); };
  $("replace-go").onclick = function () { install(true); };
  $("install-skip").onclick = function () { go("home"); };

  // ---- home ----
  var RESTART_LINE = Array.prototype.map.call($("restart-line").childNodes, function (n) { return n.cloneNode(true); });
  ENTER.home = function () {
    $("home-press").hidden = true;
    $("home-restart").hidden = true;
    put.apply(null, [$("restart-line")].concat(RESTART_LINE.map(function (n) { return n.cloneNode(true); })));
    $("home-next").hidden = true;
    $("home-others").hidden = true;
    $("home-bar").style.width = "0";
    job("/api/home", {}, function (f, msg) {
      $("home-bar").style.width = Math.round(f * 100) + "%";
      if (msg) put($("home-status"), busy(msg + "…"));
    }).then(function (r) {
      if (r.other_watchers.length) {
        $("home-others").hidden = false;
        put($("home-others"), b(r.other_watchers.join(" and ")), " is also on this TV. If it is set to take over the Home button too, the two will fight: switch its override off in its own settings. It can stay installed.");
      }
      if (!r.home_on) {
        $("home-status").textContent = "";
        $("home-press").hidden = false;
      } else if (r.watcher_running) {
        put($("home-status"), good("Couch TV is your home screen."));
        $("home-next").hidden = false;
      } else {
        $("home-status").textContent = "";
        $("home-restart").hidden = false;
      }
    }, showError);
  };
  $("home-pressed").onclick = function () { go("home"); };
  $("restart-go").onclick = function () {
    $("restart-go").disabled = true;
    call("/api/restart", {}).then(function () {
      put($("restart-line"), busy("Restarting the TV. This page carries on by itself when it is back…"));
      waitForTv(0);
    }, showError);
  };
  function waitForTv(n) {
    setTimeout(function () {
      job("/api/connect", { ip: state.ip }).then(function (dev) {
        state.device = dev;
        $("restart-go").disabled = false;
        go("home");
      }, function () { if (n < 20) waitForTv(n + 1); else showError(new Error("The TV did not come back. Check it is on, then press Look again on the Find step.")); });
    }, n === 0 ? 45000 : 6000);
  }

  // ---- check ----
  ENTER.check = function () { $("check-next").hidden = true; $("check-go").disabled = false; };
  $("check-go").onclick = function () {
    $("check-go").disabled = true;
    put($("check-status"), busy("Opening Fire TV settings, then pressing Home…"));
    job("/api/check", {}).then(function (r) {
      $("check-go").disabled = false;
      if (r.ok) {
        put($("check-status"), good("Couch TV came up. Try the Home button on your remote too."));
        $("check-next").hidden = false;
      } else {
        $("check-status").textContent = "Amazon's home stayed. Going back a step to fix it…";
        setTimeout(function () { go("home"); }, 1500);
      }
    }, showError);
  };

  // ---- pair ----
  ENTER.pair = function () { $("pair-code").hidden = true; $("pair-status").textContent = ""; };
  $("pair-start").onclick = function () {
    call("/api/pair/start", {}).then(function () {
      $("pair-code").hidden = false;
      $("pin").value = "";
      $("pin").focus();
    }, showError);
  };
  $("pin-go").onclick = function () {
    put($("pair-status"), busy("Pairing…"));
    call("/api/pair", { pin: $("pin").value }).then(function () { go("personalise"); }, function (e) {
      $("pair-status").textContent = "";
      showError(e);
    });
  };
  $("pin").addEventListener("keydown", function (e) { if (e.key === "Enter") $("pin-go").click(); });

  // ---- personalise ----
  ENTER.personalise = function () {
    state.picks = [];
    call("/api/apps").then(function (r) {
      var box = $("apps");
      put(box);
      if (!r.apps.length) { put(box, h("p", "small", "Open the home once (press Home) to see your apps here.")); return; }
      r.apps.forEach(function (a) {
        if (!a.package) return;
        var btn = h("button", null, String(a.name || a.package));
        btn.onclick = function () {
          var i = state.picks.indexOf(a.package);
          if (i >= 0) state.picks.splice(i, 1); else state.picks.push(a.package);
          drawPicks();
        };
        btn.dataset.pkg = a.package;
        btn.dataset.name = String(a.name || a.package);
        box.appendChild(btn);
      });
    }, showError);
  };
  function drawPicks() {
    document.querySelectorAll("#apps button").forEach(function (btn) {
      var i = state.picks.indexOf(btn.dataset.pkg);
      if (i >= 0) put(btn, b(i + 1), btn.dataset.name); else put(btn, btn.dataset.name);
      btn.className = i >= 0 ? "primary" : "";
    });
  }
  $("city-go").onclick = function () {
    var q = $("city").value.trim();
    if (!q) return;
    put($("places"), busy("Searching…"));
    fetch("https://geocoding-api.open-meteo.com/v1/search?count=5&format=json&language=en&name=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var box = $("places");
        put(box);
        (j.results || []).forEach(function (p) {
          var btn = h("button", null, h("span", null, String(p.name)), h("small", null, [p.admin1, p.country].filter(Boolean).join(", ")));
          btn.onclick = function () {
            state.place = p;
            box.querySelectorAll("button").forEach(function (x) { x.className = ""; });
            btn.className = "primary";
          };
          box.appendChild(btn);
        });
        if (!box.children.length) box.textContent = "No place found by that name.";
      }, function () { $("places").textContent = "Could not search. Is this computer online?"; });
  };
  $("city").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); $("city-go").click(); } });
  $("save-go").onclick = function () {
    var p = state.place, body = {};
    if (p) {
      body.weather = { lat: p.latitude, lon: p.longitude, place: p.name, timezone: p.timezone || "UTC" };
      if (p.country_code) body.country = p.country_code.toUpperCase();
    }
    var people = $("people").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    if (people.length) body.people = people;
    if (state.picks.length) { body.order = state.picks; body.line = Math.min(state.picks.length, 10); }
    put($("save-status"), busy("Saving…"));
    call("/api/personalise", body).then(function () {
      put($("save-status"), good("Saved. Have a look at your TV."));
      setTimeout(function () { go("ads"); }, 900);
    }, function (e) { $("save-status").textContent = ""; showError(e); });
  };

  // ---- ads ----
  function drawAds(list) {
    var ul = $("ads");
    put(ul);
    var allOff = true;
    list.forEach(function (a) {
      ul.appendChild(h("li", a.off ? "off" : "", h("span", null, String(a.what)), h("span", null, a.off ? "off" : "on")));
      if (!a.off) allOff = false;
    });
    $("ads-go").textContent = allOff ? "Next" : "Switch them off";
    $("ads-undo").hidden = !list.some(function (a) { return a.mine; });
    return allOff;
  }
  function list_note(apps) {
    return apps.some(function (a) { return a.off; })
      ? "Undone. What is still off was switched off before, not by this setup, so it stays off."
      : "Undone. Everything is back on.";
  }
  ENTER.ads = function () {
    $("ads-status").textContent = "";
    call("/api/ads", {}).then(function (r) { drawAds(r.apps); }, showError);
  };
  $("ads-go").onclick = function () {
    if ($("ads-go").textContent === "Next") return go("done");
    put($("ads-status"), busy("Switching them off…"));
    call("/api/ads", { action: "off" }).then(function (r) {
      drawAds(r.apps);
      put($("ads-status"), good("Done."));
    }, showError);
  };
  $("ads-undo").onclick = function () {
    put($("ads-status"), busy("Switching back on what this setup switched off…"));
    call("/api/ads", { action: "undo" }).then(function (r) {
      drawAds(r.apps);
      $("ads-status").textContent = list_note(r.apps);
    }, showError);
  };

  // ---- close ----
  var closed = false;
  document.querySelectorAll("[data-quit]").forEach(function (b) {
    b.onclick = function () {
      b.disabled = true;
      call("/api/quit", {}).then(function () {
        closed = true;
        go("closed");
        document.getElementById("dots").style.visibility = "hidden";
      }, function (e) { b.disabled = false; showError(e); });
    };
  });

  // ---- undo everything ----
  $("setup-start").onclick = function () { state.mode = "setup"; go("adb"); };
  $("undo-start").onclick = function () { state.mode = "undo"; go("adb"); };
  ENTER.undo = function () {
    var ul = $("undo-list");
    put(ul, h("li", null, busy("Looking at the TV…")));
    $("undo-status").textContent = "";
    $("undo-go").disabled = true;
    $("undo-bar").parentNode.hidden = true;
    $("undo-device").textContent = state.device ? state.device.name : "Fire TV";
    call("/api/undo/plan", {}).then(function (p) {
      var items = [];
      if (p.app.installed) items.push(h("li", null, b("Couch TV is removed"), ", and Amazon's home is on the Home button again."));
      else if (p.watcher_listed) items.push(h("li", null, "Couch TV's leftover ", b("Home watcher"), " is switched off."));
      if (p.ads_off.length) items.push(h("li", null, b(p.ads_off.length + " Amazon apps are switched back on"), ": " + p.ads_off.join(", ") + "."));
      if (!items.length) {
        put(ul, h("li", null, "Nothing to undo: Couch TV is not on this TV and Amazon's apps are all on."));
        return;
      }
      put.apply(null, [ul].concat(items));
      $("undo-go").disabled = false;
    }, showError);
  };
  $("undo-go").onclick = function () {
    $("undo-go").disabled = true;
    $("undo-bar").parentNode.hidden = false;
    job("/api/undo", {}, function (f, msg) {
      $("undo-bar").style.width = Math.round(f * 100) + "%";
      if (msg) put($("undo-status"), busy(msg + "…"));
    }).then(function (r) {
      $("undone-other").hidden = true;
      if (!r.amazon_home && r.other_watchers.length) {
        $("undone-other").hidden = false;
        put($("undone-other"), "Couch TV is gone, but ", b(r.other_watchers.join(" and ")), " is still set to take over the Home button. Switch that off in its own settings, or uninstall it, to get Amazon's home.");
      }
      go("undone");
    }, function (e) { $("undo-go").disabled = false; showError(e); });
  };

  // Tells the setup program this page is still open (it stops by itself a few minutes after it closes).
  setInterval(function () { if (!closed) call("/api/ping").catch(function () {}); }, 20000);
  call("/api/ping").catch(function () {});

  // #adb, #find, #allow or #done open that step straight away (handy for the README's pictures).
  var start = location.hash.slice(1);
  go(["adb", "find", "allow", "done"].indexOf(start) >= 0 ? start : "welcome");
})();
