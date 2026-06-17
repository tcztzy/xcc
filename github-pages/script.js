const year = document.querySelector("#year");
if (year) {
  year.textContent = String(new Date().getFullYear());
}

function copyText(text, button) {
  navigator.clipboard
    .writeText(text)
    .then(() => {
      const previous = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = previous;
      }, 1400);
    })
    .catch(() => {
      button.textContent = "Select text";
    });
}

document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", () => {
    copyText(button.getAttribute("data-copy") || "", button);
  });
});

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = document.getElementById(button.getAttribute("data-copy-target") || "");
    copyText(target ? target.value.trim() : "", button);
  });
});
