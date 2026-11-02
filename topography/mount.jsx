import React from 'react';
import { createRoot } from 'react-dom/client';
import Topography from './Topography.jsx';

const mount = document.getElementById('role-topography');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

class TopographyBoundary extends React.Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.warn('Echo WebGL topography failed; the static contour fallback remains visible.', error);
    if (mount) mount.dataset.topographyStatus = 'fallback';
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

if (mount) {
  try {
    const root = createRoot(mount);
    root.render(
      <TopographyBoundary>
        <Topography
          color="#4f7cff"
          lineCount={22}
          lineWidth={1.2}
          elevation={1}
          foreground={0.2}
          tilt={32}
          speed={reducedMotion ? 0 : 0.25}
          direction="forward"
          glow={0.6}
          depthOfField={0.4}
          fog={0.35}
          hoverEffect="lift"
          clickEffect="pulse"
          mouseInteraction={!reducedMotion}
          intro={!reducedMotion}
        />
      </TopographyBoundary>
    );
    mount.dataset.topographyStatus = 'mounted';

    // Read the component's real canvas after its first paint. This lets the
    // page report whether the animated renderer or static fallback is active.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const canvas = mount.querySelector('canvas');
      const gl = canvas?.getContext('webgl2');
      mount.dataset.topographyStatus = gl && canvas.width > 0 && canvas.height > 0 ? 'webgl2-ready' : 'fallback';
    }));
  } catch (error) {
    console.warn('Echo opening background could not start; using the static contour fallback.', error);
    mount.dataset.topographyStatus = 'fallback';
  }
}
