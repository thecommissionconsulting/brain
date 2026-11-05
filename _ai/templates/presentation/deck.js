/* Shared company deck chrome: arrows / click / hash / fullscreen. */
(() => {
  const slides = [...document.querySelectorAll(".slide")];
  const bar = document.getElementById("bar");
  const count = document.getElementById("count");
  if (!slides.length) return;
  let i = 0;

  function show(n) {
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach((s, k) => s.classList.toggle("active", k === i));
    document.body.classList.toggle("on-title", slides[i].classList.contains("title"));
    if (bar) bar.style.width = ((i + 1) / slides.length) * 100 + "%";
    if (count) count.textContent = i + 1 + " / " + slides.length;
    history.replaceState(null, "", "#" + (i + 1));
  }

  document.addEventListener("keydown", (e) => {
    if (["ArrowRight", "ArrowDown", "PageDown", " "].includes(e.key)) {
      e.preventDefault();
      show(i + 1);
    } else if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace"].includes(e.key)) {
      e.preventDefault();
      show(i - 1);
    } else if (e.key === "Home") show(0);
    else if (e.key === "End") show(slides.length - 1);
    else if (e.key === "f" || e.key === "F") {
      if (!document.fullscreenElement) document.documentElement.requestFullscreen();
      else document.exitFullscreen();
    }
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest("a, button, pre")) return;
    show(e.clientX > window.innerWidth / 2 ? i + 1 : i - 1);
  });

  window.goToSlide = show;
  window.addEventListener("hashchange", () => {
    const n = parseInt(location.hash.replace("#", ""), 10);
    if (Number.isFinite(n) && n >= 1) show(n - 1);
  });
  const start = parseInt(location.hash.replace("#", ""), 10);
  show(Number.isFinite(start) && start >= 1 ? start - 1 : 0);
})();
