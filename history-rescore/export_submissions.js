// export_submissions.js
//
// Paste into the browser console on https://virtualembryo.ai/challenge/account/submissions, after the
// submissions list is fully expanded (use "show all" if the table is paginated). It keeps the scored rows
// and downloads submissions.csv with the columns submitted,task,file,board,board_score.
//
// The board column is a guess. Rows where it is blank must be filled in by hand before running
// rescore.py (or pass --guess-blank to rescore.py, which applies the same rules and warns for each guess).
//
// Board rules:
//   task "T1"                       -> T1:val
//   task "T2 · embryo"              -> T2:embryo:val_interp
//   task "T2 · heart", file mentions E8.5 or interp    -> T2:heart:val_interp
//   task "T2 · heart", file mentions E10.5 or extrap   -> T2:heart:val_extrap
//   task "T2 · heart", both or neither                 -> blank (set by hand)
//   task "T3"                       -> T3:gata4
//   anything else                   -> blank (set by hand)
//
// Test-phase boards are not guessed; fill those rows with the key from the panel index.
//
// The DOM selectors are: the main table (or the first table), its thead th cells for column names, and
// tbody tr / td for rows. Each cell is read as its first line of text.

(function () {
  "use strict";

  const COLUMNS = ["submitted", "task", "file", "board", "board_score"];
  const NEEDED_HEADERS = ["SUBMITTED", "TASK", "FILE", "STATUS", "SCORE"];

  function normaliseTask(task) {
    return String(task || "").replace(/[^A-Za-z0-9]+/g, " ").trim().replace(/\s+/g, " ").toLowerCase();
  }

  function guessBoard(task, fileName) {
    const t = normaliseTask(task);
    const f = String(fileName || "");
    if (/^t1\b/.test(t)) return "T1:val";
    if (/^t3\b/.test(t)) return "T3:gata4";
    if (/^t2 embryo\b/.test(t)) return "T2:embryo:val_interp";
    if (/^t2 heart\b/.test(t)) {
      const interp = /E8\.5|interp/i.test(f);
      const extrap = /E10\.5|extrap/i.test(f);
      if (interp && !extrap) return "T2:heart:val_interp";
      if (extrap && !interp) return "T2:heart:val_extrap";
    }
    return "";
  }

  function firstLine(el) {
    if (!el) return "";
    const txt = el.innerText != null ? el.innerText : (el.textContent || "");
    return String(txt).trim().split("\n")[0].trim();
  }

  function parseRows(table) {
    let headers = Array.from(table.querySelectorAll("thead th")).map((th) => firstLine(th).toUpperCase());
    if (NEEDED_HEADERS.some((n) => headers.indexOf(n) < 0)) {
      // Column order of the submissions table as of 2026-10-08, used if the header cells are not found.
      headers = ["SUBMITTED", "TASK", "FILE", "STATUS", "SCORE", "ACTIONS"];
      console.warn("Header cells not found; assuming the column order " + headers.join(", "));
    }
    const col = (name) => headers.indexOf(name);
    const missing = NEEDED_HEADERS.filter((n) => col(n) < 0);
    if (missing.length) {
      throw new Error("Missing column(s) " + missing.join(", ") + ". Found: " + headers.join(" | "));
    }
    const rows = [];
    const skipped = { unscored: 0, noScore: 0 };
    for (const tr of Array.from(table.querySelectorAll("tbody tr"))) {
      const cells = Array.from(tr.querySelectorAll("td"));
      if (!cells.length) continue;
      const get = (name) => firstLine(cells[col(name)]);
      const status = get("STATUS");
      if (!/scored/i.test(status) || /unscored/i.test(status)) {
        skipped.unscored += 1;
        continue;
      }
      const scoreText = get("SCORE");
      const score = Number(scoreText);
      if (scoreText === "" || !Number.isFinite(score)) {
        skipped.noScore += 1;
        continue;
      }
      const task = get("TASK");
      const file = get("FILE");
      rows.push({
        submitted: get("SUBMITTED"),
        task: task,
        file: file,
        board: guessBoard(task, file),
        board_score: scoreText,
      });
    }
    return { rows: rows, skipped: skipped };
  }

  function csvEscape(v) {
    const s = v == null ? "" : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  function toCsv(rows) {
    const lines = [COLUMNS.join(",")];
    for (const r of rows) lines.push(COLUMNS.map((c) => csvEscape(r[c])).join(","));
    return lines.join("\r\n") + "\r\n";
  }

  function run() {
    const table = document.querySelector("main table") || document.querySelector("table");
    if (!table) {
      console.error("No submissions table found. Expand the list, then run this again.");
      return 0;
    }
    const result = parseRows(table);
    const rows = result.rows;
    console.info(
      "Kept " + rows.length + " scored rows; skipped " + result.skipped.unscored +
      " unscored and " + result.skipped.noScore + " without a numeric score."
    );
    const blank = rows.filter((r) => r.board === "");
    if (blank.length) {
      console.warn(
        blank.length + " rows have a blank board. Fill the board column by hand before rescoring:",
        blank.map((r) => r.file + " (" + r.task + ")")
      );
    }
    const blob = new Blob([toCsv(rows)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "submissions.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    window.vecSubmissionRows = rows;
    return rows.length;
  }

  const api = { normaliseTask: normaliseTask, guessBoard: guessBoard, parseRows: parseRows, toCsv: toCsv };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    run();
  }
})();
