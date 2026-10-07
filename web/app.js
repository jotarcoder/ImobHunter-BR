(() => {
  const app = document.getElementById('floatingApp');
  const handle = document.getElementById('dragHandle');
  const demoSearch = document.getElementById('demoSearch');
  const toast = document.getElementById('demoToast');
  if (!app || !handle) return;

  let dragging = false;
  let pointerId = null;
  let startX = 0;
  let startY = 0;
  let originX = 0;
  let originY = 0;
  let offsetX = 0;
  let offsetY = 0;

  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

  const startDrag = (event) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    dragging = true;
    pointerId = event.pointerId;
    startX = event.clientX;
    startY = event.clientY;
    originX = offsetX;
    originY = offsetY;
    app.classList.add('dragging');
    handle.setPointerCapture(pointerId);
    event.preventDefault();
  };

  const moveDrag = (event) => {
    if (!dragging || event.pointerId !== pointerId) return;
    const bounds = app.parentElement.getBoundingClientRect();
    const maxX = Math.max(0, (bounds.width - app.offsetWidth) / 2 + 100);
    const maxY = Math.max(0, (bounds.height - app.offsetHeight) / 2 + 120);
    offsetX = clamp(originX + event.clientX - startX, -maxX, maxX);
    offsetY = clamp(originY + event.clientY - startY, -maxY, maxY);
    app.style.transform = `translate3d(${offsetX}px,${offsetY}px,0)`;
  };

  const stopDrag = (event) => {
    if (!dragging || (event && event.pointerId !== pointerId)) return;
    dragging = false;
    pointerId = null;
    app.classList.remove('dragging');
    if (event) {
      try { handle.releasePointerCapture(event.pointerId); } catch (_) {}
    }
  };

  handle.addEventListener('pointerdown', startDrag);
  handle.addEventListener('pointermove', moveDrag);
  handle.addEventListener('pointerup', stopDrag);
  handle.addEventListener('pointercancel', stopDrag);
  handle.addEventListener('lostpointercapture', () => stopDrag());

  app.addEventListener('keydown', (event) => {
    const step = event.shiftKey ? 30 : 12;
    if (!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowUp') offsetY -= step;
    if (event.key === 'ArrowDown') offsetY += step;
    if (event.key === 'ArrowLeft') offsetX -= step;
    if (event.key === 'ArrowRight') offsetX += step;
    const bounds = app.parentElement.getBoundingClientRect();
    const maxX = Math.max(0, (bounds.width - app.offsetWidth) / 2 + 100);
    const maxY = Math.max(0, (bounds.height - app.offsetHeight) / 2 + 120);
    offsetX = clamp(offsetX, -maxX, maxX);
    offsetY = clamp(offsetY, -maxY, maxY);
    app.style.transform = `translate3d(${offsetX}px,${offsetY}px,0)`;
  });

  if (demoSearch) {
    demoSearch.addEventListener('click', () => {
      const values = [
        ['12.458','32','2.341','94%'],
        ['13.106','35','2.518','96%'],
        ['11.972','31','2.208','93%']
      ];
      const next = values[Math.floor(Math.random() * values.length)];
      ['statProperties','statSources','statIptu','statConfidence'].forEach((id, index) => {
        const el = document.getElementById(id);
        if (el) el.textContent = next[index];
      });
      if (toast) {
        toast.classList.add('show');
        window.clearTimeout(window.__imobToastTimer);
        window.__imobToastTimer = window.setTimeout(() => toast.classList.remove('show'), 2800);
      }
    });
  }
})();