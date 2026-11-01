let draggedCard = null;

async function updateCardStatus(cardId, status) {
  const response = await fetch(`/api/admin/messages/${cardId}/status`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ status }),
  });

  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    const detail = payload.errors?.join(" ") || "Não foi possível atualizar o status.";
    throw new Error(detail);
  }
  return payload.item;
}

function refreshColumnCounts() {
  document.querySelectorAll(".kanban-column").forEach((column) => {
    const count = column.querySelectorAll(".kanban-card").length;
    const badge = column.querySelector(".kanban-column-header span");
    if (badge) {
      badge.textContent = String(count);
    }
  });
}

function moveCardElement(card, status) {
  const dropzone = document.querySelector(`[data-kanban-dropzone="${status}"]`);
  if (!dropzone) {
    return;
  }
  dropzone.prepend(card);
  card.dataset.currentStatus = status;
  refreshColumnCounts();
}

function showKanbanError(message) {
  window.alert(message);
}

document.querySelectorAll("[data-confirm-submit]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirmSubmit)) {
      event.preventDefault();
    }
  });
});

document.querySelectorAll(".kanban-card").forEach((card) => {
  card.addEventListener("dragstart", (event) => {
    draggedCard = card;
    card.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.dataset.cardId);
  });

  card.addEventListener("dragend", () => {
    card.classList.remove("is-dragging");
    draggedCard = null;
  });
});

document.querySelectorAll(".kanban-dropzone").forEach((dropzone) => {
  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("is-over");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("is-over");
  });

  dropzone.addEventListener("drop", async (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-over");
    const card = draggedCard;
    if (!card) {
      return;
    }

    const nextStatus = dropzone.dataset.kanbanDropzone;
    const previousStatus = card.dataset.currentStatus;
    const previousParent = card.parentElement;
    moveCardElement(card, nextStatus);

    try {
      await updateCardStatus(card.dataset.cardId, nextStatus);
    } catch (error) {
      if (previousParent) {
        previousParent.prepend(card);
      }
      card.dataset.currentStatus = previousStatus;
      refreshColumnCounts();
      showKanbanError(error.message);
    }
  });
});

document.querySelectorAll("[data-move-card]").forEach((button) => {
  button.addEventListener("click", async () => {
    const card = document.querySelector(`[data-card-id="${button.dataset.moveCard}"]`);
    if (!card) {
      return;
    }

    const previousStatus = card.dataset.currentStatus;
    const previousParent = card.parentElement;
    const nextStatus = button.dataset.targetStatus;
    moveCardElement(card, nextStatus);

    try {
      await updateCardStatus(card.dataset.cardId, nextStatus);
    } catch (error) {
      if (previousParent) {
        previousParent.prepend(card);
      }
      card.dataset.currentStatus = previousStatus;
      refreshColumnCounts();
      showKanbanError(error.message);
    }
  });
});
