// Runtime chung cho template: co chữ cho vừa khung, báo tràn chữ, tua animation theo thời gian (ms).
window.__VA = {
  isOverflow(el) {
    return el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2;
  },
  fit() {
    document.querySelectorAll('[data-fit]').forEach(el => {
      let scale = 1;
      el.style.setProperty('--fit', scale);
      while (this.isOverflow(el) && scale > 0.6) {
        scale -= 0.05;
        el.style.setProperty('--fit', scale.toFixed(2));
      }
    });
  },
  overflow() {
    return [...document.querySelectorAll('[data-fit]')]
      .filter(el => el.textContent.trim() && this.isOverflow(el))
      .map(el => el.dataset.fit);
  },
  seek(ms) {
    document.getAnimations().forEach(a => { a.pause(); a.currentTime = ms; });
    if (typeof window.__tick === 'function') window.__tick(ms);
  },
};
document.addEventListener('DOMContentLoaded', () => window.__VA.fit());
