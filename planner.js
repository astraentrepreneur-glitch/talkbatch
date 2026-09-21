"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const video = $("preview");
  let source = null;
  let objectURL = null;
  let groups = [{title: "Talk 1", ranges: [["0", "1"]]}];

  function slug(title) {
    return title.normalize("NFKD").replace(/[^\x00-\x7f]/g, "")
      .replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-+|-+$/g, "")
      .toLowerCase().slice(0, 60).replace(/-+$/g, "") || "untitled";
  }
  function filename(index, title) {
    return `${String(index + 1).padStart(3, "0")}-${slug(title)}.webm`;
  }
  function parseTime(text) {
    const parts = String(text).trim().split(":");
    if (parts.length > 3 || parts.some((p, i) => !(i === parts.length - 1
      ? /^\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i : /^\d+$/).test(p))) {
      throw new Error("Use seconds, MM:SS or HH:MM:SS (optional decimal seconds).");
    }
    const values = parts.map(Number);
    if (values.some(v => !Number.isFinite(v)) ||
        (parts.length > 1 && values.slice(1).some(v => v >= 60))) {
      throw new Error("Minute/second components after a colon must be below 60.");
    }
    return values.reduce((sum, value) => sum * 60 + value, 0);
  }
  function fields(value, allowed, required, label) {
    if (!value || typeof value !== "object" || Array.isArray(value) ||
        Object.keys(value).some(k => !allowed.includes(k)) ||
        required.some(k => !Object.prototype.hasOwnProperty.call(value, k))) {
      throw new Error(`${label} has missing or unknown fields.`);
    }
  }
  function validate(plan) {
    fields(plan, ["version", "source", "groups"], ["version", "source", "groups"], "Plan");
    if (plan.version !== 1) throw new Error("Only plan version 1 is supported.");
    fields(plan.source, ["name", "size", "duration"], ["name"], "Source");
    const s = plan.source;
    if (typeof s.name !== "string" || !s.name || [...s.name].length > 255 ||
        [".", ".."].includes(s.name) || /[\\/\x00-\x1f\x7f]/.test(s.name)) {
      throw new Error("Source name must be a filename, not a path.");
    }
    if ("size" in s && (!Number.isSafeInteger(s.size) || s.size <= 0)) {
      throw new Error("Source size must be a positive safe integer.");
    }
    if ("duration" in s && (typeof s.duration !== "number" || !Number.isFinite(s.duration) || s.duration <= 0)) {
      throw new Error("Source duration must be positive and finite.");
    }
    if (!Array.isArray(plan.groups) || !plan.groups.length || plan.groups.length > 30) {
      throw new Error("Use 1 to 30 output groups.");
    }
    let total = 0;
    plan.groups.forEach((group, i) => {
      fields(group, ["title", "ranges"], ["title", "ranges"], `Group ${i + 1}`);
      if (typeof group.title !== "string" || !group.title.trim() ||
          [...group.title].length > 80 || /[\x00-\x1f\x7f]/.test(group.title)) {
        throw new Error(`Group ${i + 1}: title must be 1 to 80 characters without control characters.`);
      }
      if (!Array.isArray(group.ranges) || !group.ranges.length || group.ranges.length > 10) {
        throw new Error(`Group ${i + 1}: use 1 to 10 ranges.`);
      }
      total += group.ranges.length;
      group.ranges.forEach((range, j) => {
        if (!Array.isArray(range) || range.length !== 2 ||
            range.some(v => typeof v !== "number" || !Number.isFinite(v))) {
          throw new Error(`Group ${i + 1}, range ${j + 1}: expected numeric [start, end].`);
        }
        if (range[0] < 0 || range[1] - range[0] < 0.1 - 1e-9 ||
            ("duration" in s && range[1] > s.duration + 0.001)) {
          throw new Error(`Group ${i + 1}, range ${j + 1}: require at least 0.1s within source duration.`);
        }
      });
    });
    if (total > 120) throw new Error("Use at most 120 ranges in the plan.");
    return plan;
  }
  function buildPlan() {
    if (!source) throw new Error("Choose a source file or load an existing plan first.");
    return validate({version: 1, source: {...source}, groups: groups.map(g => ({
      title: g.title, ranges: g.ranges.map(r => r.map(parseTime))
    }))});
  }
  function status(message, good = false) {
    $("plan-status").textContent = message;
    $("plan-status").className = good ? "ok" : "error";
  }
  function refresh() {
    $("queue").replaceChildren();
    document.querySelectorAll(".filename").forEach((element, i) => {
      element.textContent = filename(i, groups[i].title);
    });
    try {
      const plan = buildPlan();
      let total = 0;
      plan.groups.forEach((g, i) => {
        const seconds = g.ranges.reduce((sum, r) => sum + r[1] - r[0], 0);
        total += seconds;
        const item = document.createElement("li");
        item.textContent = `${filename(i, g.title)} - ${g.ranges.length} range(s), ${seconds.toFixed(3)} seconds`;
        $("queue").append(item);
      });
      $("download").disabled = false;
      status(`${plan.groups.length} output(s), ${total.toFixed(3)} seconds planned. CLI will probe the actual file.`, true);
    } catch (error) {
      $("download").disabled = true;
      status(error.message);
    }
  }
  function button(text, action, className = "secondary", disabled = false) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = text; b.className = className; b.disabled = disabled;
    b.addEventListener("click", action);
    return b;
  }
  function move(list, index, delta) {
    [list[index], list[index + delta]] = [list[index + delta], list[index]];
    render();
  }
  function field(text, value, changed, className = "") {
    const label = document.createElement("label");
    label.className = className; label.append(document.createTextNode(text));
    const input = document.createElement("input");
    input.type = "text"; input.value = value; input.setAttribute("aria-label", text);
    input.addEventListener("input", () => { changed(input.value); refresh(); });
    label.append(input);
    return label;
  }
  function render() {
    $("groups").replaceChildren();
    groups.forEach((group, i) => {
      const article = document.createElement("article"); article.className = "group";
      const tools = document.createElement("div"); tools.className = "card-tools";
      const heading = document.createElement("h3"); heading.textContent = `Output ${i + 1}`;
      const actions = document.createElement("div");
      actions.append(button("Move up", () => move(groups, i, -1), "secondary", i === 0),
        button("Move down", () => move(groups, i, 1), "secondary", i === groups.length - 1),
        button("Remove output", () => { groups.splice(i, 1); render(); }, "danger"));
      tools.append(heading, actions); article.append(tools);
      article.append(field(`Output ${i + 1} title`, group.title, v => { group.title = v; }, "title-label"));
      const name = document.createElement("code"); name.className = "filename"; article.append(name);
      group.ranges.forEach((range, j) => {
        const row = document.createElement("div"); row.className = "range";
        row.append(field(`Range ${j + 1} start`, range[0], v => { range[0] = v; }),
          field(`Range ${j + 1} end`, range[1], v => { range[1] = v; }));
        const unavailable = video.readyState < 1 || !Number.isFinite(video.currentTime);
        row.append(button("In = playhead", () => { range[0] = video.currentTime.toFixed(3); render(); }, "secondary", unavailable),
          button("Out = playhead", () => { range[1] = video.currentTime.toFixed(3); render(); }, "secondary", unavailable),
          button("Earlier", () => move(group.ranges, j, -1), "secondary", j === 0),
          button("Later", () => move(group.ranges, j, 1), "secondary", j === group.ranges.length - 1),
          button("Remove range", () => { group.ranges.splice(j, 1); render(); }, "danger"));
        article.append(row);
      });
      article.append(button("+ Add range", () => { group.ranges.push(["0", "1"]); render(); },
        "secondary", group.ranges.length >= 10));
      $("groups").append(article);
    });
    $("add-group").disabled = groups.length >= 30;
    refresh();
  }

  $("add-group").addEventListener("click", () => {
    groups.push({title: `Talk ${groups.length + 1}`, ranges: [["0", "1"]]}); render();
  });
  $("source-file").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (!file) return;
    if (!/\.(mp4|mov|mkv|webm)$/i.test(file.name)) {
      status("Choose an MP4, MOV, MKV or WebM file."); event.target.value = ""; return;
    }
    if (source && (source.name !== file.name || ("size" in source && source.size !== file.size))) {
      if (!window.confirm("This is a different source. Clear the current output groups?")) {
        event.target.value = ""; return;
      }
      groups = [{title: "Talk 1", ranges: [["0", "1"]]}];
    }
    if (objectURL) URL.revokeObjectURL(objectURL);
    source = {name: file.name, size: file.size};
    objectURL = URL.createObjectURL(file);
    $("source-status").textContent = `${file.name} (${file.size.toLocaleString()} bytes), loaded locally.`;
    video.src = objectURL; render();
  });
  video.addEventListener("loadedmetadata", () => {
    if (source && Number.isFinite(video.duration) && video.duration > 0) {
      source.duration = video.duration;
      $("source-status").textContent = `${source.name} - ${video.duration.toFixed(3)}s. Browser-local preview.`;
    }
    render();
  });
  video.addEventListener("error", () => {
    $("source-status").textContent = "Browser preview unavailable. You can enter ranges manually; CLI validation is still required.";
    render();
  });
  $("plan-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 1024 * 1024) throw new Error("Plan exceeds 1 MiB.");
      const plan = validate(JSON.parse(await file.text()));
      if (objectURL && source && (source.name !== plan.source.name ||
          ("size" in plan.source && source.size !== plan.source.size))) {
        throw new Error("Plan belongs to a different source. Open that source first.");
      }
      if (objectURL && Number.isFinite(video.duration) && "duration" in plan.source &&
          Math.abs(video.duration - plan.source.duration) > 0.25) {
        throw new Error("Plan duration differs from the loaded video.");
      }
      source = {...plan.source};
      if (objectURL && Number.isFinite(video.duration) && video.duration > 0) {
        source.duration = video.duration;
      }
      groups = plan.groups.map(g => ({title: g.title, ranges: g.ranges.map(r => r.map(String))}));
      if (!objectURL) $("source-status").textContent = `Plan for ${source.name}. Choose the matching video to preview.`;
      render();
    } catch (error) {
      status(`Plan not loaded: ${error.message}`);
    }
    event.target.value = "";
  });
  $("download").addEventListener("click", () => {
    try {
      const plan = buildPlan();
      const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2) + "\n"], {type: "application/json"}));
      const a = document.createElement("a");
      a.href = url; a.download = `${slug(plan.source.name.replace(/\.[^.]+$/, ""))}-talkbatch.json`;
      document.body.append(a); a.click(); a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      status("Plan downloaded. Next: CLI dry-run, then export to a new directory.", true);
    } catch (error) { status(error.message); }
  });
  window.addEventListener("beforeunload", () => { if (objectURL) URL.revokeObjectURL(objectURL); });
  window.TalkBatch = Object.freeze({parseTime, slug, filename, validate});
  render();
})();
