(function () {
  "use strict";
  var KEY = document.querySelector('meta[name="setup-key"]').content;
  var STEPS = ["welcome", "adb", "find", "allow", "install", "home", "check", "pair", "personalise", "ads", "done"];
  var $ = function (id) { return document.getElementById(id); };
  var state = { ip: null, device: null, picks: [], place: null, mode: "setup" };

  // ---- talking to the Mac side ----
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
  function busy(text) { return '<span class="spin"></span>' + text; }

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
    $("find-status").innerHTML = busy("Looking on your Wi-Fi…");
    $("found").innerHTML = "";
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
        var b = document.createElement("button");
        if (i === 0) b.className = "primary";
        b.innerHTML = "<span>" + (t.name || "Fire TV") + "</span><small>" + t.ip + "</small>";
        b.onclick = function () { connect(t.ip); };
        $("found").appendChild(b);
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
    $("allow-status").innerHTML = busy("Tick <b>Always allow from this computer</b>, then press <b>Allow</b>.");
    job("/api/connect", { ip: ip }).then(function (dev) {
      state.device = dev;
      if (!dev.supported) {
        $("allow-status").innerHTML = "This is a <b>" + dev.name + "</b> (" + dev.os + "). This setup is made for Fire TV sticks, so it stops here.";
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
    $("device-line").innerHTML = "Connected to your <b>" + d.name + "</b> (" + d.os + ").";
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
      if (msg) $("install-status").innerHTML = busy(msg + "…");
    }).then(function (r) {
      $("install-status").innerHTML = '<span class="good">✓ Couch TV ' + r.apk.version + " is on the TV.</span>";
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
  var RESTART_LINE = $("restart-line").innerHTML;
  ENTER.home = function () {
    $("home-press").hidden = true;
    $("home-restart").hidden = true;
    $("restart-line").innerHTML = RESTART_LINE;
    $("home-next").hidden = true;
    $("home-others").hidden = true;
    $("home-bar").style.width = "0";
    job("/api/home", {}, function (f, msg) {
      $("home-bar").style.width = Math.round(f * 100) + "%";
      if (msg) $("home-status").innerHTML = busy(msg + "…");
    }).then(function (r) {
      if (r.other_watchers.length) {
        $("home-others").hidden = false;
        $("home-others").innerHTML = "<b>" + r.other_watchers.join(" and ") + "</b> is also on this TV. If it is set to take over the Home button too, the two will fight: switch its override off in its own settings. It can stay installed.";
      }
      if (!r.home_on) {
        $("home-status").textContent = "";
        $("home-press").hidden = false;
      } else if (r.watcher_running) {
        $("home-status").innerHTML = '<span class="good">✓ Couch TV is your home screen.</span>';
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
      $("restart-line").innerHTML = busy("Restarting the TV. This page carries on by itself when it is back…");
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
    $("check-status").innerHTML = busy("Pressing Home…");
    job("/api/check", {}).then(function (r) {
      $("check-go").disabled = false;
      if (r.ok) {
        $("check-status").innerHTML = '<span class="good">✓ Couch TV came up. Try the Home button on your remote too.</span>';
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
    $("pair-status").innerHTML = busy("Pairing…");
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
      box.innerHTML = "";
      if (!r.apps.length) { box.innerHTML = '<p class="small">Open the home once (press Home) to see your apps here.</p>'; return; }
      r.apps.forEach(function (a) {
        if (!a.package) return;
        var b = document.createElement("button");
        b.textContent = a.name || a.package;
        b.onclick = function () {
          var i = state.picks.indexOf(a.package);
          if (i >= 0) state.picks.splice(i, 1); else state.picks.push(a.package);
          drawPicks();
        };
        b.dataset.pkg = a.package;
        box.appendChild(b);
      });
    }, showError);
  };
  function drawPicks() {
    document.querySelectorAll("#apps button").forEach(function (b) {
      var i = state.picks.indexOf(b.dataset.pkg);
      var name = b.textContent.replace(/^\d+/, "");
      b.innerHTML = (i >= 0 ? "<b>" + (i + 1) + "</b>" : "") + name;
      b.className = i >= 0 ? "primary" : "";
    });
  }
  $("city-go").onclick = function () {
    var q = $("city").value.trim();
    if (!q) return;
    $("places").innerHTML = busy("Searching…");
    fetch("https://geocoding-api.open-meteo.com/v1/search?count=5&format=json&language=en&name=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var box = $("places");
        box.innerHTML = "";
        (j.results || []).forEach(function (p) {
          var b = document.createElement("button");
          b.innerHTML = "<span>" + p.name + "</span><small>" + [p.admin1, p.country].filter(Boolean).join(", ") + "</small>";
          b.onclick = function () {
            state.place = p;
            box.querySelectorAll("button").forEach(function (x) { x.className = ""; });
            b.className = "primary";
          };
          box.appendChild(b);
        });
        if (!box.children.length) box.textContent = "No place found by that name.";
      }, function () { $("places").textContent = "Could not search. Is this Mac online?"; });
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
    $("save-status").innerHTML = busy("Saving…");
    call("/api/personalise", body).then(function () {
      $("save-status").innerHTML = '<span class="good">✓ Saved. Have a look at your TV.</span>';
      setTimeout(function () { go("ads"); }, 900);
    }, function (e) { $("save-status").textContent = ""; showError(e); });
  };

  // ---- ads ----
  function drawAds(list) {
    var ul = $("ads");
    ul.innerHTML = "";
    var allOff = true;
    list.forEach(function (a) {
      var li = document.createElement("li");
      li.className = a.off ? "off" : "";
      li.innerHTML = "<span>" + a.what + "</span><span>" + (a.off ? "off" : "on") + "</span>";
      ul.appendChild(li);
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
    $("ads-status").innerHTML = busy("Switching them off…");
    call("/api/ads", { action: "off" }).then(function (r) {
      drawAds(r.apps);
      $("ads-status").innerHTML = '<span class="good">✓ Done.</span>';
    }, showError);
  };
  $("ads-undo").onclick = function () {
    $("ads-status").innerHTML = busy("Switching back on what this setup switched off…");
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
    ul.innerHTML = "<li>" + busy("Looking at the TV…") + "</li>";
    $("undo-status").textContent = "";
    $("undo-go").disabled = true;
    $("undo-bar").parentNode.hidden = true;
    $("undo-device").textContent = state.device ? state.device.name : "Fire TV";
    call("/api/undo/plan", {}).then(function (p) {
      var items = [];
      if (p.app.installed) items.push("<b>Couch TV is removed</b>, and Amazon's home is on the Home button again.");
      else if (p.watcher_listed) items.push("Couch TV's leftover <b>Home watcher</b> is switched off.");
      if (p.ads_off.length) items.push("<b>" + p.ads_off.length + " Amazon apps are switched back on</b>: " + p.ads_off.join(", ") + ".");
      if (!items.length) {
        ul.innerHTML = "<li>Nothing to undo: Couch TV is not on this TV and Amazon's apps are all on.</li>";
        return;
      }
      ul.innerHTML = items.map(function (t) { return "<li>" + t + "</li>"; }).join("");
      $("undo-go").disabled = false;
    }, showError);
  };
  $("undo-go").onclick = function () {
    $("undo-go").disabled = true;
    $("undo-bar").parentNode.hidden = false;
    job("/api/undo", {}, function (f, msg) {
      $("undo-bar").style.width = Math.round(f * 100) + "%";
      if (msg) $("undo-status").innerHTML = busy(msg + "…");
    }).then(function (r) {
      $("undone-other").hidden = true;
      if (!r.amazon_home && r.other_watchers.length) {
        $("undone-other").hidden = false;
        $("undone-other").innerHTML = "Couch TV is gone, but <b>" + r.other_watchers.join(" and ") + "</b> is still set to take over the Home button. Switch that off in its own settings, or uninstall it, to get Amazon's home.";
      }
      go("undone");
    }, function (e) { $("undo-go").disabled = false; showError(e); });
  };

  // Tells the Mac side this page is still open (it stops by itself a few minutes after it closes).
  setInterval(function () { if (!closed) call("/api/ping").catch(function () {}); }, 20000);
  call("/api/ping").catch(function () {});

  // #adb, #find, #allow or #done open that step straight away (handy for the README's pictures).
  var start = location.hash.slice(1);
  go(["adb", "find", "allow", "done"].indexOf(start) >= 0 ? start : "welcome");
})();
