/**
 * Chart.js 4.4.0 NaN layout fix
 *
 * Root cause: ticks.padding resolves to undefined, causing fit() to compute
 * NaN for scale width/height (formula: labelSize + 2*undefined = NaN).
 * NaN width/height → chartArea dimensions null → blank canvas.
 *
 * Fix: patch Chart.Scale.prototype.fit directly (synchronously at load time,
 * before any charts are created) to sanitize NaN/null results.
 * Chart.Scale is the base class for all scales in Chart.js 4.x.
 */
(function () {
  if (typeof Chart === 'undefined' || !Chart.Scale) return;

  const origFit = Chart.Scale.prototype.fit;
  Chart.Scale.prototype.fit = function () {
    origFit.apply(this, arguments);

    // Sanitize NaN/null width for left/right positioned scales
    if (!this.isHorizontal() && !isFinite(this.width)) {
      try {
        const sizes = this._getLabelSizes();
        const labelW = (sizes && sizes.widest && sizes.widest.width) || 0;
        const pad = (this.options && this.options.ticks && +this.options.ticks.padding) || 3;
        this.width = Math.min(this.maxWidth || 200, labelW + pad * 2 + 8);
      } catch (e) {
        this.width = this.maxWidth || 0;
      }
    }

    // Sanitize NaN/null height for top/bottom positioned scales
    if (this.isHorizontal() && !isFinite(this.height)) {
      try {
        const sizes = this._getLabelSizes();
        const labelH = (sizes && sizes.highest && sizes.highest.height) || 0;
        const pad = (this.options && this.options.ticks && +this.options.ticks.padding) || 3;
        this.height = Math.min(this.maxHeight || 100, labelH + pad * 2 + 8);
      } catch (e) {
        this.height = this.maxHeight || 0;
      }
    }
  };

  // Belt-and-suspenders: sanitize NaN margins in layout manager
  if (Chart.layouts && Chart.layouts.update) {
    const origLayoutsUpdate = Chart.layouts.update;
    Chart.layouts.update = function (chart, width, height, padding) {
      const scales = chart && chart.scales ? Object.values(chart.scales) : [];
      const saved = new Map();
      for (const scale of scales) {
        const origUpdate = scale.update;
        saved.set(scale, origUpdate);
        scale.update = function (maxW, maxH, margins) {
          return origUpdate.call(
            this,
            isFinite(maxW) ? maxW : (this.maxWidth || 0),
            isFinite(maxH) ? maxH : (this.maxHeight || 0),
            margins ? {
              left:   isFinite(margins.left)   ? margins.left   : 0,
              right:  isFinite(margins.right)  ? margins.right  : 0,
              top:    isFinite(margins.top)    ? margins.top    : 0,
              bottom: isFinite(margins.bottom) ? margins.bottom : 0,
            } : margins
          );
        };
      }
      const result = origLayoutsUpdate.call(this, chart, width, height, padding);
      for (const [scale, origUpdate] of saved) {
        scale.update = origUpdate;
      }
      return result;
    };
  }
})();
