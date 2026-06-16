"use strict";

// --- small DOM helpers -------------------------------------------------

const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const statusText = $("statusText");

function setStatus(text, mode) {
  statusText.textContent = text;
  statusEl.classList.toggle("error", mode === "error");
  statusEl.classList.toggle("ready", mode === "ready");
}

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

async function fileToBytes(file) {
  return new Uint8Array(await file.arrayBuffer());
}

function wireDrop(dropEl, inputEl, onFile) {
  dropEl.addEventListener("click", () => inputEl.click());
  inputEl.addEventListener("change", () => {
    if (inputEl.files[0]) onFile(inputEl.files[0]);
  });
  ["dragenter", "dragover"].forEach((evt) =>
    dropEl.addEventListener(evt, (e) => {
      e.preventDefault();
      dropEl.classList.add("drag");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropEl.addEventListener(evt, (e) => {
      e.preventDefault();
      dropEl.classList.remove("drag");
    })
  );
  dropEl.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  });
}

// --- tabs ----------------------------------------------------------------

function wireTabs() {
  const tabs = [
    { btn: $("tabHide"), panel: $("panelHide") },
    { btn: $("tabReveal"), panel: $("panelReveal") },
    { btn: $("tabAnalyze"), panel: $("panelAnalyze") },
    { btn: $("tabKeys"), panel: $("panelKeys") },
  ];
  for (const { btn } of tabs) {
    btn.addEventListener("click", () => {
      for (const t of tabs) {
        const active = t.btn === btn;
        t.btn.setAttribute("aria-selected", String(active));
        t.panel.hidden = !active;
      }
    });
  }
}

function wireToggle(checkboxId, sectionId) {
  const checkbox = $(checkboxId);
  const section = $(sectionId);
  checkbox.addEventListener("change", () => {
    section.hidden = !checkbox.checked;
  });
}

// --- Pyodide setup ---------------------------------------------------------

let pyodide = null;
let steg = null; // the imported `steganographer` package, as a JS-callable proxy
let signingMod = null; // steganographer.signing
let analyzeMod = null; // steganographer.analyze

async function boot() {
  try {
    setStatus("Downloading Python runtime…");
    pyodide = await loadPyodide();

    setStatus("Loading numpy, Pillow and cryptography…");
    await pyodide.loadPackage(["numpy", "Pillow", "cryptography", "micropip"]);

    setStatus("Installing steganographer…");
    const micropip = pyodide.pyimport("micropip");
    // built fresh from source by .github/workflows/pages.yml on every deploy.
    // micropip needs a real version in the wheel filename (a symbolic name like
    // "latest" isn't a valid PEP 440 version, it just fails to parse) -- bump
    // this alongside __version__ in src/steganographer/__init__.py
    await micropip.install("./dist/steganographer-4.0.0-py3-none-any.whl", { deps: false });
    await micropip.install("reedsolo");

    steg = pyodide.pyimport("steganographer");
    signingMod = pyodide.pyimport("steganographer.signing");
    analyzeMod = pyodide.pyimport("steganographer.analyze");

    setStatus("Ready");
    statusEl.classList.add("ready");
    for (const id of ["tabHide", "tabReveal", "tabAnalyze", "tabKeys", "hideBtn", "revealBtn", "analyzeBtn", "keygenBtn"]) {
      $(id).disabled = false;
    }
  } catch (err) {
    console.error(err);
    setStatus(`Could not start: ${describeError(err)}`, "error");
  }
}

// --- hide tab --------------------------------------------------------------

const state = {
  cover: null, // { name, bytes }
  toHide: null, // { name, bytes }
  stego: null, // { name, bytes }
  signKey: null, // { name, bytes } -- private key to sign with
  decoyFile: null, // { name, bytes }
  verifyKey: null, // { name, bytes } -- public key to require on extract
  analyzeImage: null, // { name, bytes }
};

function showMsg(el, text, kind) {
  el.replaceChildren();
  if (!text) return;
  const div = document.createElement("div");
  div.className = `msg ${kind}`;
  div.textContent = text;
  el.appendChild(div);
}

// row with a label span and a download link, built with DOM methods rather
// than innerHTML -- both name and size can come from a file the user picked
// themselves, and shouldn't be interpolated into an HTML string
function resultRow(label, url, downloadName) {
  const row = document.createElement("div");
  row.className = "row";
  const info = document.createElement("span");
  info.className = "info";
  info.textContent = label;
  const a = document.createElement("a");
  a.className = "download";
  a.href = url;
  a.download = downloadName;
  a.textContent = "Download";
  row.append(info, a);
  return row;
}

function updateCapacityLine() {
  const line = $("capacityLine");
  if (!state.cover || !steg) {
    line.hidden = true;
    return;
  }
  try {
    pyodide.FS.writeFile("/tmp/cover_probe", state.cover.bytes);
    const capacity = steg.capacity("/tmp/cover_probe");
    line.hidden = false;
    line.textContent = `Capacity in lsb mode: ${humanSize(capacity)}`;
    line.classList.remove("over");
  } catch (e) {
    line.hidden = true;
  }
}

wireDrop($("coverDrop"), $("coverInput"), async (file) => {
  state.cover = { name: file.name, bytes: await fileToBytes(file) };
  $("coverName").textContent = file.name;
  $("coverSub").textContent = humanSize(file.size);
  const img = document.createElement("img");
  img.src = URL.createObjectURL(file);
  $("coverDrop").querySelector(".icon, img")?.replaceWith(img);
  updateCapacityLine();
});

wireDrop($("fileDrop"), $("fileInput"), async (file) => {
  state.toHide = { name: file.name, bytes: await fileToBytes(file) };
  $("fileName").textContent = file.name;
  $("fileSub").textContent = humanSize(file.size);
});

wireToggle("signCheck", "signFields");
wireToggle("decoyCheck", "decoyFields");
wireToggle("verifyCheck", "verifyFields");

wireDrop($("signKeyDrop"), $("signKeyInput"), async (file) => {
  state.signKey = { name: file.name, bytes: await fileToBytes(file) };
  $("signKeyName").textContent = file.name;
});

wireDrop($("decoyDrop"), $("decoyInput"), async (file) => {
  state.decoyFile = { name: file.name, bytes: await fileToBytes(file) };
  $("decoyName").textContent = file.name;
  $("decoySub").textContent = humanSize(file.size);
});

wireDrop($("verifyKeyDrop"), $("verifyKeyInput"), async (file) => {
  state.verifyKey = { name: file.name, bytes: await fileToBytes(file) };
  $("verifyKeyName").textContent = file.name;
});

// writes a key file to the Pyodide FS and loads it, turning "needs a
// passphrase" into a clear message instead of a raw traceback
function loadSigningKey(fsPath, keyState, passphrase) {
  pyodide.FS.writeFile(fsPath, keyState.bytes);
  try {
    return signingMod.load_private_key(fsPath, passphrase || null);
  } catch (err) {
    if (describeError(err).includes("PassphraseRequired") || /passphrase/i.test(String(err.message))) {
      throw new Error(`${keyState.name} needs its passphrase.`);
    }
    throw new Error(`${keyState.name}: ${describeError(err)}`);
  }
}

function showHideResult(resultEl, blob, outName, note) {
  const url = URL.createObjectURL(blob);
  resultEl.hidden = false;
  resultEl.replaceChildren();
  if (outName.endsWith(".png")) {
    const img = document.createElement("img");
    img.src = url;
    resultEl.appendChild(img);
  }
  resultEl.appendChild(resultRow(`${outName} · ${humanSize(blob.size)}${note ? " · " + note : ""}`, url, outName));
}

$("hideBtn").addEventListener("click", async () => {
  const msgEl = $("hideMsg");
  const resultEl = $("hideResult");
  showMsg(msgEl, "", "");
  resultEl.hidden = true;

  if (!state.cover) return showMsg(msgEl, "Pick a cover image first.", "error");
  if (!state.toHide) return showMsg(msgEl, "Pick a file to hide first.", "error");

  const useDecoy = $("decoyCheck").checked;
  const mode = useDecoy ? "lsb" : document.querySelector('input[name="mode"]:checked').value;
  const password = $("hidePassword").value || null;

  if (useDecoy) {
    if (!state.decoyFile) return showMsg(msgEl, "Pick a decoy file first.", "error");
    if (!password) return showMsg(msgEl, "A decoy needs a real password too.", "error");
    if (!$("decoyPassword").value) return showMsg(msgEl, "Pick a decoy password.", "error");
    if ($("decoyPassword").value === password) return showMsg(msgEl, "The decoy and real passwords must differ.", "error");
  }

  const btn = $("hideBtn");
  btn.disabled = true;
  btn.textContent = "Hiding…";

  try {
    const suffix = mode === "lsb" ? ".png" : (state.cover.name.match(/\.[^.]+$/) || [".png"])[0];
    pyodide.FS.writeFile("/tmp/cover_in", state.cover.bytes);

    let outBytes, note;
    if (useDecoy) {
      const decoyData = pyodide.toPy(state.decoyFile.bytes).tobytes();
      const realData = pyodide.toPy(state.toHide.bytes).tobytes();
      const outPath = steg.hide_deniable.callKwargs(
        "/tmp/cover_in",
        decoyData,
        $("decoyPassword").value,
        realData,
        password,
        "/tmp/out.png",
        { decoy_filename: state.decoyFile.name, real_filename: state.toHide.name }
      );
      outBytes = pyodide.FS.readFile(outPath.toString());
      note = "with a decoy";
    } else {
      const data = pyodide.toPy(state.toHide.bytes).tobytes();
      const kwargs = { password: password, mode: mode, filename: state.toHide.name };
      if ($("adaptiveCheck").checked) kwargs.adaptive = true;
      if ($("signCheck").checked) {
        if (!state.signKey) throw new Error("Pick a private key to sign with.");
        kwargs.sign_with = loadSigningKey("/tmp/signkey", state.signKey, $("signPassphrase").value);
      }
      // a trailing plain object is a positional arg to a PyProxy call, not
      // kwargs -- callKwargs is what actually maps it to Python's password=/
      // mode=/filename=/... keyword-only parameters
      const outPath = steg.hide.callKwargs("/tmp/cover_in", data, `/tmp/out${suffix}`, kwargs);
      outBytes = pyodide.FS.readFile(outPath.toString());
      note = kwargs.sign_with ? "signed" : null;
    }

    const blob = new Blob([outBytes], { type: suffix === ".png" ? "image/png" : "application/octet-stream" });
    const outName = `${state.cover.name.replace(/\.[^.]+$/, "")}_steg0${suffix}`;
    showHideResult(resultEl, blob, outName, note);

    showMsg(
      msgEl,
      useDecoy
        ? "Hidden. Extract with the real password for your file, the decoy password for the decoy."
        : "Hidden. Extract it back with the Reveal tab and the same password.",
      "ok"
    );
  } catch (err) {
    console.error(err);
    showMsg(msgEl, describeError(err), "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Hide file";
  }
});

// --- reveal tab --------------------------------------------------------------

wireDrop($("stegoDrop"), $("stegoInput"), async (file) => {
  state.stego = { name: file.name, bytes: await fileToBytes(file) };
  $("stegoName").textContent = file.name;
});

$("revealBtn").addEventListener("click", async () => {
  const msgEl = $("revealMsg");
  const resultEl = $("revealResult");
  showMsg(msgEl, "", "");
  resultEl.hidden = true;

  if (!state.stego) return showMsg(msgEl, "Pick an image first.", "error");

  const password = $("revealPassword").value || null;
  const useVerify = $("verifyCheck").checked;
  if (useVerify && !state.verifyKey) return showMsg(msgEl, "Pick a public key to require, or turn that off.", "error");

  const btn = $("revealBtn");
  btn.disabled = true;
  btn.textContent = "Extracting…";

  try {
    pyodide.FS.writeFile("/tmp/stego_in", state.stego.bytes);

    let name, bytes, note;
    try {
      const kwargs = { password: password };
      if (useVerify) {
        pyodide.FS.writeFile("/tmp/verifykey", state.verifyKey.bytes);
        kwargs.signed_by = signingMod.load_public_key("/tmp/verifykey");
      }
      const revealed = steg.reveal_file.callKwargs("/tmp/stego_in", kwargs);
      name = revealed.name || "extracted.bin";
      bytes = new Uint8Array(revealed.data.toJs());
      note = revealed.signer ? `signed by ${signingMod.fingerprint(revealed.signer)}` : null;
    } catch (firstErr) {
      // the normal format wasn't found (or didn't verify) -- if a password
      // was given and verification wasn't required, it might be a decoy
      // layer instead, which has no format of its own to fail loudly on
      if (useVerify || !password) throw firstErr;
      const decoy = steg.reveal_decoy("/tmp/stego_in", password);
      if (decoy === undefined || decoy === null) throw firstErr;
      name = decoy[0] || "extracted.bin";
      bytes = new Uint8Array(decoy[1].toJs());
      note = "decoy layer";
    }

    const blob = new Blob([bytes]);
    const url = URL.createObjectURL(blob);

    resultEl.hidden = false;
    resultEl.replaceChildren(resultRow(`${name} · ${humanSize(bytes.length)}${note ? " · " + note : ""}`, url, name));
    showMsg(msgEl, "Found it.", "ok");
  } catch (err) {
    console.error(err);
    showMsg(msgEl, describeError(err), "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Extract file";
  }
});

// --- analyze tab -----------------------------------------------------------

wireDrop($("analyzeDrop"), $("analyzeInput"), async (file) => {
  state.analyzeImage = { name: file.name, bytes: await fileToBytes(file) };
  $("analyzeName").textContent = file.name;
});

function statRow(label, value) {
  const row = document.createElement("div");
  row.className = "stat";
  const k = document.createElement("span");
  k.className = "k";
  k.textContent = label;
  const v = document.createElement("span");
  v.className = "v";
  v.textContent = value;
  row.append(k, v);
  return row;
}

$("analyzeBtn").addEventListener("click", async () => {
  const msgEl = $("analyzeMsg");
  const resultEl = $("analyzeResult");
  showMsg(msgEl, "", "");
  resultEl.hidden = true;

  if (!state.analyzeImage) return showMsg(msgEl, "Pick an image first.", "error");

  const btn = $("analyzeBtn");
  btn.disabled = true;
  btn.textContent = "Analyzing…";

  try {
    pyodide.FS.writeFile("/tmp/analyze_in", state.analyzeImage.bytes);
    const report = analyzeMod.analyze("/tmp/analyze_in");

    const stats = document.createElement("div");
    stats.className = "stats";
    stats.append(
      statRow("Chi-square (whole image)", report.chi_square.toFixed(3)),
      statRow("Chi-square (most suspicious window)", report.peak_chi_square.toFixed(3)),
      statRow("RS discriminant", report.rs.discriminant.toFixed(4)),
      statRow("Estimated capacity used", `${(report.estimated_fraction * 100).toFixed(0)}%`)
    );

    const verdict = report.verdict;
    const badge = document.createElement("div");
    badge.className = `badge ${verdict === "no strong signal of hidden data" ? "clean" : verdict === "suspicious" ? "suspicious" : "flagged"}`;
    badge.textContent = verdict;

    resultEl.hidden = false;
    resultEl.replaceChildren(stats, badge);
    showMsg(msgEl, "This is a rough check, not a substitute for a dedicated steganalysis tool.", "ok");
  } catch (err) {
    console.error(err);
    showMsg(msgEl, describeError(err), "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyze";
  }
});

// --- keys tab ----------------------------------------------------------------

$("keygenBtn").addEventListener("click", async () => {
  const msgEl = $("keygenMsg");
  const resultEl = $("keygenResult");
  showMsg(msgEl, "", "");
  resultEl.hidden = true;

  const btn = $("keygenBtn");
  btn.disabled = true;
  btn.textContent = "Generating…";

  try {
    // clear out any key from an earlier click -- signing.generate refuses
    // to overwrite an existing path
    for (const p of ["/tmp/newkey", "/tmp/newkey.pub"]) {
      try {
        pyodide.FS.unlink(p);
      } catch (_) {
        /* didn't exist yet, fine */
      }
    }
    const passphrase = $("keygenPassphrase").value || null;
    const key = signingMod.generate("/tmp/newkey", passphrase);
    const fingerprint = signingMod.fingerprint(key.public_key());

    const privateBytes = pyodide.FS.readFile("/tmp/newkey");
    const publicBytes = pyodide.FS.readFile("/tmp/newkey.pub");
    // an explicit type keeps Chromium from guessing one and appending its
    // own extension (it otherwise turns "id_ed25519" into "id_ed25519.txt")
    const privateUrl = URL.createObjectURL(new Blob([privateBytes], { type: "application/x-pem-file" }));
    const publicUrl = URL.createObjectURL(new Blob([publicBytes], { type: "text/plain" }));

    resultEl.hidden = false;
    resultEl.replaceChildren();
    const fp = document.createElement("div");
    fp.className = "fingerprint";
    fp.textContent = fingerprint;
    resultEl.append(
      fp,
      resultRow("id_ed25519 (private, keep this)", privateUrl, "id_ed25519"),
      resultRow("id_ed25519.pub (public, share this)", publicUrl, "id_ed25519.pub")
    );
    showMsg(msgEl, "Made. The private key never left this tab.", "ok");
  } catch (err) {
    console.error(err);
    showMsg(msgEl, describeError(err), "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate key pair";
  }
});

// --- errors --------------------------------------------------------------

function describeError(err) {
  const message = (err && err.message) || String(err);
  // pyodide wraps Python exceptions with a full traceback; the last "Type: message"
  // line is the part worth showing someone who isn't reading Python tracebacks
  const lines = message.trim().split("\n");
  const last = lines[lines.length - 1] || message;
  const match = last.match(/^\S*Error:\s*(.+)$/) || last.match(/^\S*Error\s*(.*)$/);
  return match ? match[1] || last : last;
}

wireTabs();
boot();
