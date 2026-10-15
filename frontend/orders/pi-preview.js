/* Editable commercial snapshot; the server owns identity, bank details and totals. */
window.createPiPreview = function (host, api, json, onIssued) {
  let state = null,
    issued = null,
    busy = false,
    inputs = [],
    paper,
    printFrame,
    status,
    toolbar;
  const node = (tag, text, className) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (className) n.className = className;
    return n;
  };
  function field(parent, label, value, path, multiline = false, type = "text") {
    const wrap = node("label", undefined, "pi-field");
    wrap.append(node("span", label));
    const input = node(multiline ? "textarea" : "input");
    if (!multiline) input.type = type;
    input.value = value ?? "";
    input.dataset.piField = path;
    input.setAttribute("aria-label", label);
    if (multiline) input.rows = path.startsWith("delivery.") ? 9 : 3;
    if (type === "number") {
      input.min = "0";
      input.step = path.endsWith("quantity") ? "1" : "0.01";
    }
    input.oninput = () => {
      status.textContent =
        "Unsaved preview changes. Update preview to review calculated totals and the printed page.";
      printFrame.hidden = true;
      paper.hidden = false;
    };
    wrap.append(input);
    parent.append(wrap);
    inputs.push({ input, path });
    return input;
  }
  function image(parent, name) {
    const img = node("img");
    img.src = "data:image/png;base64," + state.document.assets[name];
    img.alt = name.replace(".png", "").replaceAll("_", " ");
    parent.append(img);
  }
  function collect() {
    const doc = state.document,
      data = {
        date: doc.date,
        order: {},
        delivery: {},
        shipping_charges: doc.totals.shipping,
        lines: doc.totals.lines.map((line) =>
          Object.fromEntries(
            [
              "id",
              "sku",
              "description",
              "hsn_code",
              "item_condition",
              "uom",
              "quantity",
              "unit_price",
            ].map((k) => [k, line[k]]),
          ),
        ),
      };
    for (const { input, path } of inputs) {
      const parts = path.split(".");
      let target = data;
      for (const part of parts.slice(0, -1)) target = target[part];
      target[parts.at(-1)] = input.value;
    }
    return data;
  }
  async function save() {
    state = await api(
      state.base + "/" + state.preview_id,
      json("PUT", collect()),
    ).then((result) => ({ ...result, base: state.base }));
    render();
  }
  async function run(callback) {
    if (busy) return;
    busy = true;
    toolbar.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      await callback();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
      status.focus();
    } finally {
      busy = false;
      toolbar.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  }
  function button(label, callback, primary = false) {
    const b = node("button", label, "btn-sm" + (primary ? " btn-add" : ""));
    b.type = "button";
    b.onclick = () => run(callback);
    toolbar.append(b);
    return b;
  }
  function render() {
    host.replaceChildren();
    host.hidden = false;
    inputs = [];
    toolbar = node("div", undefined, "pi-preview-toolbar");
    host.append(toolbar);
    button("Close preview", async () => {
      host.hidden = true;
    });
    if (!issued) {
      button("Update preview", save);
      button("Edit invoice", async () => { printFrame.hidden = true; paper.hidden = false; });
      button("PDF print preview", async () => {
        await save();
        paper.hidden = true;
        printFrame.hidden = false;
        printFrame.src = state.pdf_url + "?v=" + Date.now();
      });
    }
    for (const format of ["xlsx", "pdf"])
      button(
        "Generate " + format.toUpperCase(),
        async () => {
          if (!issued) {
            await save();
            issued = await api(
              state.base.replace("/preview", "/issue"),
              json("POST", { preview_id: state.preview_id }),
            );
            await onIssued(issued);
            render();
          }
          const a = node("a");
          a.href = issued[format + "_url"];
          a.download = "";
          host.append(a);
          a.click();
          a.remove();
        },
        true,
      );
    status = node(
      "p",
      issued
        ? "PI " +
            issued.reference +
            " issued. Both downloads use this saved invoice."
        : "Edit fields directly below, then review the PDF print preview. Changes apply to this PI only.",
      "pi-preview-status",
    );
    status.role = "status";
    status.tabIndex = -1;
    host.append(status);
    const scroller = node("div", undefined, "pi-paper-scroll");
    paper = node("article", undefined, "pi-paper");
    scroller.append(paper);
    host.append(scroller);
    printFrame = node("iframe");
    printFrame.title = "Exact PI PDF print preview";
    printFrame.className = "pi-print-frame";
    printFrame.hidden = true;
    host.append(printFrame);
    const doc = state.document,
      order = doc.order,
      total = doc.totals;
    image(paper, "header.png");
    paper.append(node("h2", "PROFORMA INVOICE"));
    const overview = node("div", undefined, "pi-overview");
    overview.append(
      node("div", doc.company.seller.join("\n"), "pi-preformatted"),
    );
    const identity = node("div");
    identity.append(
      node("strong", doc.reference),
      node(
        "p",
        "Currency: " + doc.currency + " · Prepared by: " + doc.prepared_by,
      ),
    );
    field(identity, "PI date", doc.date, "date", false, "date");
    field(identity, "PO reference", order.po_reference, "order.po_reference");
    overview.append(identity);
    paper.append(overview);
    const commercial = node("div", undefined, "pi-commercial");
    for (const [key, label] of [
      ["payment_terms", "Payment terms"],
      ["delivery_terms", "Delivery terms"],
      ["destination", "Destination"],
      ["delivery_time", "Delivery time"],
      ["dispatch_method", "Dispatch"],
    ])
      field(commercial, label, order[key], "order." + key);
    paper.append(commercial);
    const parties = node("div", undefined, "pi-preview-parties");
    for (const [key, label] of [
      ["consignee_text", "Consignee"],
      ["buyer_text", "Buyer details"],
      ["notify_text", "Notify details"],
    ])
      field(parties, label, doc.delivery[key], "delivery." + key, true);
    paper.append(parties);
    const table = node("table", undefined, "pi-preview-lines"),
      head = node("thead"),
      hr = node("tr");
    for (const label of [
      "Item / Description",
      "HSN / Condition",
      "Qty / UOM",
      "Rate (" + doc.currency + ")",
      "Amount",
    ])
      hr.append(node("th", label));
    head.append(hr);
    table.append(head);
    const body = node("tbody");
    total.lines.forEach((line, index) => {
      const row = node("tr");
      for (const group of [
        [
          ["sku", "SKU"],
          ["description", "Description"],
        ],
        [
          ["hsn_code", "HSN code"],
          ["item_condition", "Condition"],
        ],
        [
          ["quantity", "Quantity"],
          ["uom", "UOM"],
        ],
        [["unit_price", "Unit price"]],
      ]) {
        const td = node("td");
        for (const [key, label] of group)
          field(
            td,
            label,
            line[key],
            `lines.${index}.${key}`,
            ["description"].includes(key),
            ["quantity", "unit_price"].includes(key) ? "number" : "text",
          );
        row.append(td);
      }
      row.append(node("td", line.line_total, "pi-line-amount"));
      body.append(row);
    });
    table.append(body);
    paper.append(table);
    const totals = node("div", undefined, "pi-preview-totals");
    for (const [label, key] of [
      ["Subtotal", "subtotal"],
      ["GST", "tax"],
      ["Grand total (" + doc.currency + ")", "grand_total"],
    ]) {
      if (key === "tax" && total.tax === "0.00") continue;
      totals.append(node("div", label), node("strong", total[key]));
    }
    field(
      totals,
      "Shipping (" + doc.currency + ")",
      total.shipping,
      "shipping_charges",
      false,
      "number",
    );
    paper.append(
      totals,
      node("p", "Amount in words: " + total.amount_in_words, "pi-amount-words"),
    );
    paper.append(
      node("h3", "Bank details"),
      node("div", doc.company.bank.join("\n"), "pi-preformatted"),
      node("p", doc.company.bank_charges || ""),
    );
    paper.append(
      node("h3", "Terms & conditions"),
      node(
        "div",
        doc.company.terms[doc.currency]
          .map((t) => t.replace(/^(\s*\d+[.)]\s*)?PAYMENT\b.*/i, (_, prefix) => (prefix || "") + "PAYMENT " + order.payment_terms))
          .join("\n"),
        "pi-preformatted",
      ),
    );
    field(
      paper,
      "Delivery instructions",
      doc.delivery.instructions,
      "delivery.instructions",
      true,
    );
    field(paper, "Order notes", order.notes, "order.notes", true);
    const signatures = node("div", undefined, "pi-signatures");
    image(signatures, "payment_options.png");
    image(signatures, "signature.png");
    paper.append(signatures);
    image(paper, "address.png");
    if (issued) for (const { input } of inputs) input.disabled = true;
  }
  return {
    open(data, base) {
      state = { ...data, base };
      issued = null;
      render();
      host.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    reset() {
      host.hidden = true;
      host.replaceChildren();
      state = null;
      issued = null;
    },
  };
};
