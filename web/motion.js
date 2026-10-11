(() => {
  'use strict';
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(pointer: fine)');
  const stage = document.querySelector('.hero-stage');
  const app = document.querySelector('.floating-app');
  let scrollFrame = 0;

  // Reveal content with a measured, editorial cadence; keep all text in the DOM.
  const revealItems = document.querySelectorAll('.hero-copy, main section, .hero h1, main section h2');
  if ('IntersectionObserver' in window && !reduce.matches) {
    revealItems.forEach((item, index) => {
      item.classList.add('reveal-ready');
      item.style.setProperty('--reveal-delay', Math.min(index * 35, 140) + 'ms');
    });
    const observer = new IntersectionObserver((entries, obs) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.14, rootMargin: '0px 0px -4% 0px' });
    revealItems.forEach(item => observer.observe(item));
  }

  // Scroll-scrubbed cinematic composition: no heavy video download, GPU-friendly transforms.
  const progress = document.createElement('div');
  progress.className = 'scroll-progress';
  progress.setAttribute('aria-hidden', 'true');
  document.body.appendChild(progress);
  const updateScroll = () => {
    scrollFrame = 0;
    const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const overall = Math.min(1, Math.max(0, window.scrollY / max));
    progress.style.transform = 'scaleX(' + overall.toFixed(4) + ')';
    if (!stage || reduce.matches) return;
    const rect = stage.getBoundingClientRect();
    const span = Math.max(1, rect.height + window.innerHeight);
    const p = Math.min(1, Math.max(0, (window.innerHeight - rect.top) / span));
    stage.style.setProperty('--scene-progress', p.toFixed(4));
    stage.querySelectorAll('.motion-reel').forEach((el, i) => {
      const drift = (p - .5) * (i === 1 ? -34 : 26);
      el.style.setProperty('--scroll-drift', drift.toFixed(1) + 'px');
    });
    if (app) app.style.setProperty('--scroll-drift', ((p - .5) * -22).toFixed(1) + 'px');
    document.querySelectorAll('main section').forEach((section, i) => {
      const r = section.getBoundingClientRect();
      const center = (r.top + r.height * .5 - window.innerHeight * .5) / Math.max(1, window.innerHeight);
      section.style.setProperty('--section-drift', (Math.max(-1, Math.min(1, center)) * (i % 2 ? 4 : -4)).toFixed(1) + 'px');
    });
  };
  const requestScroll = () => {
    if (!scrollFrame) scrollFrame = requestAnimationFrame(updateScroll);
  };
  window.addEventListener('scroll', requestScroll, { passive: true });
  window.addEventListener('resize', requestScroll, { passive: true });
  requestScroll();

  // Restrained 3D tracking on the product mock-up.
  if (stage && app && !reduce.matches) {
    let raf = 0, tx = 0, ty = 0, cx = 0, cy = 0;
    const render = () => {
      cx += (tx - cx) * .12; cy += (ty - cy) * .12;
      app.style.setProperty('--tilt-x', cy.toFixed(2) + 'deg');
      app.style.setProperty('--tilt-y', cx.toFixed(2) + 'deg');
      if (Math.abs(tx - cx) > .08 || Math.abs(ty - cy) > .08) raf = requestAnimationFrame(render);
      else raf = 0;
    };
    stage.addEventListener('pointermove', event => {
      const r = stage.getBoundingClientRect();
      tx = Math.max(-5, Math.min(5, ((event.clientX - r.left) / r.width - .5) * 9));
      ty = Math.max(-4, Math.min(4, -((event.clientY - r.top) / r.height - .5) * 7));
      if (!raf) raf = requestAnimationFrame(render);
    }, { passive: true });
    stage.addEventListener('pointerleave', () => { tx = 0; ty = 0; if (!raf) raf = requestAnimationFrame(render); }, { passive: true });
  }

  // Tilt cards only on fine pointers; no transforms on touch devices.
  if (finePointer.matches && !reduce.matches) {
    document.querySelectorAll('[data-tilt]').forEach(el => {
      const depth = Number(el.dataset.depth || 10);
      el.addEventListener('pointermove', event => {
        const r = el.getBoundingClientRect();
        const x = (event.clientX - r.left) / r.width - .5;
        const y = (event.clientY - r.top) / r.height - .5;
        el.style.setProperty('--rx', (-y * 2.8).toFixed(2) + 'deg');
        el.style.setProperty('--ry', (x * 3.4).toFixed(2) + 'deg');
        el.style.setProperty('--tz', Math.min(depth, 10) + 'px');
        el.style.setProperty('--field-x', ((x + .5) * 100).toFixed(1) + '%');
        el.style.setProperty('--field-y', ((y + .5) * 100).toFixed(1) + '%');
      }, { passive: true });
      el.addEventListener('pointerleave', () => {
        ['--rx','--ry'].forEach(k => el.style.setProperty(k, '0deg'));
        el.style.setProperty('--tz', '0px');
        el.style.setProperty('--field-x', '50%');
        el.style.setProperty('--field-y', '50%');
      }, { passive: true });
    });
  }


  // Preserve the landing's existing 3D CTA interaction while keeping it restrained.
  if (finePointer.matches && !reduce.matches) {
    document.querySelectorAll('.button').forEach(button => {
      button.addEventListener('pointermove', event => {
        const r = button.getBoundingClientRect();
        const x = (event.clientX - r.left) / r.width - .5;
        const y = (event.clientY - r.top) / r.height - .5;
        button.style.setProperty('--button-rx', (-y * 4).toFixed(2) + 'deg');
        button.style.setProperty('--button-ry', (x * 5).toFixed(2) + 'deg');
        button.style.setProperty('--button-z', '3px');
      }, { passive: true });
      button.addEventListener('pointerleave', () => {
        button.style.setProperty('--button-rx', '0deg');
        button.style.setProperty('--button-ry', '0deg');
        button.style.setProperty('--button-z', '0px');
      }, { passive: true });
    });
  }

  // Magnetic cursor: decorative only; native pointer remains on touch and reduced-motion setups.
  if (!reduce.matches && finePointer.matches) {
    const cursor = document.createElement('div');
    cursor.className = 'magnetic-cursor';
    cursor.setAttribute('aria-hidden', 'true');
    document.body.appendChild(cursor);
    document.body.classList.add('magnetic-cursor-enabled');
    const targets = [...document.querySelectorAll('.button, .download, .navlinks a, .policy-card > summary')];
    targets.forEach(el => el.setAttribute('data-magnetic', ''));
    let x = -80, y = -80, tx = x, ty = y, raf = 0, active = null;
    const render = () => {
      x += (tx - x) * .24; y += (ty - y) * .24;
      cursor.style.transform = 'translate3d(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px,0) translate(-50%,-50%)';
      if (Math.abs(tx - x) > .25 || Math.abs(ty - y) > .25) raf = requestAnimationFrame(render);
      else raf = 0;
    };
    const move = event => {
      tx = event.clientX; ty = event.clientY;
      const next = event.target instanceof Element ? event.target.closest('[data-magnetic]') : null;
      if (next !== active) {
        active?.classList.remove('magnetic-near');
        active = next;
        active?.classList.add('magnetic-near');
        cursor.classList.toggle('is-active', Boolean(active));
      }
      if (active) {
        const r = active.getBoundingClientRect();
        active.style.setProperty('--magnetic-x', Math.max(-4, Math.min(4, (event.clientX - r.left - r.width/2) * .055)).toFixed(1) + 'px');
        active.style.setProperty('--magnetic-y', Math.max(-4, Math.min(4, (event.clientY - r.top - r.height/2) * .055)).toFixed(1) + 'px');
      }
      cursor.classList.add('is-visible');
      if (!raf) raf = requestAnimationFrame(render);
    };
    const leave = () => {
      tx = -80; ty = -80; cursor.classList.remove('is-visible','is-active');
      active?.classList.remove('magnetic-near');
      active?.style.setProperty('--magnetic-x','0px');
      active?.style.setProperty('--magnetic-y','0px');
      active = null;
      if (!raf) raf = requestAnimationFrame(render);
    };
    window.addEventListener('pointermove', move, { passive: true });
    document.documentElement.addEventListener('pointerleave', leave, { passive: true });
    window.addEventListener('blur', leave);
  }
})();