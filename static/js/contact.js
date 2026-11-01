(function () {
  "use strict";

  const form = document.getElementById("request");

  if (!form) {
    return;
  }

  const feedback = document.getElementById("contact-feedback");
  const submitButton = form.querySelector("button[type='submit']");

  function setFeedback(message, state) {
    feedback.textContent = message;
    feedback.classList.remove("is-success", "is-error");

    if (state) {
      feedback.classList.add(`is-${state}`);
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();

    if (!form.checkValidity()) {
      form.reportValidity();
      setFeedback("Confira os campos obrigatórios antes de enviar.", "error");
      return;
    }

    const payload = Object.fromEntries(new FormData(form).entries());

    submitButton.disabled = true;
    setFeedback("Enviando sua mensagem...", null);

    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      });

      const result = await response.json();

      if (!response.ok) {
        setFeedback(result.error || "Não foi possível enviar a mensagem.", "error");
        return;
      }

      form.reset();
      setFeedback("Mensagem recebida. Em breve entraremos em contato.", "success");
    } catch (error) {
      setFeedback("Falha de conexão. Tente novamente em alguns instantes.", "error");
    } finally {
      submitButton.disabled = false;
    }
  });
})();
