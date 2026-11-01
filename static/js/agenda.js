"use strict";

document.querySelectorAll("[data-agenda-delete]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm("Excluir este compromisso?")) event.preventDefault();
  });
});

// Preserve edits while the GET form refreshes imported message snapshots.
const eventForm = document.querySelector(".agenda-event-form");
const importForm = document.querySelector(".agenda-import-form");
const formError = document.querySelector("#agenda-form-error");
if (eventForm && formError) {
  const showError = (message) => {
    formError.textContent = message;
    formError.hidden = false;
    formError.scrollIntoView({ block: "center" });
  };
  eventForm.addEventListener("invalid", (event) => {
    const label = event.target.labels?.[0]?.textContent.trim() || "Campo";
    showError(`${label}: ${event.target.validationMessage}`);
  }, true);
  eventForm.addEventListener("input", () => {
    eventForm.elements.namedItem("end_at").setCustomValidity("");
    formError.hidden = true;
  });
  eventForm.addEventListener("submit", (event) => {
    const start = eventForm.elements.namedItem("start_at");
    const end = eventForm.elements.namedItem("end_at");
    if (end.value && end.value <= start.value) {
      event.preventDefault();
      end.setCustomValidity("O término deve ser posterior ao início.");
      showError("O término deve ser posterior ao início.");
      end.reportValidity();
    }
  });
}
if (eventForm && importForm) {
  importForm.addEventListener("submit", () => {
    for (const name of ["title", "event_type", "start_at", "end_at", "location", "description"]) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = eventForm.elements.namedItem(name).value;
      importForm.append(input);
    }
  });
}
