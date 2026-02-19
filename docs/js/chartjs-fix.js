/**
 * Chart.js bar rendering fix
 *
 * Root cause: _stacks._top is NaN/null when chart.defaults.scale.ticks
 * was replaced instead of merged, clearing ticks.padding. This causes
 * _calculateBarValuePixels to return NaN for `base`, so bars never draw.
 *
 * Fix: patch BarController._calculateBarValuePixels to fall back to
 * computing base directly from the value scale when the result is NaN.
 */
(function () {
  if (typeof Chart === 'undefined') return;

  function applyBarFix() {
    var BarController = Chart.registry && Chart.registry.controllers && Chart.registry.controllers.get('bar');
    if (!BarController || BarController.prototype._dotpBarFixed) return;
    BarController.prototype._dotpBarFixed = true;

    var orig = BarController.prototype._calculateBarValuePixels;
    BarController.prototype._calculateBarValuePixels = function (index) {
      var result = orig.call(this, index);
      if (!result || isFinite(result.base)) return result;

      // base is NaN — compute directly from the value scale
      var vScale = this.chart.scales.y
        || (this._cachedMeta.vScale && this.chart.scales[this._cachedMeta.vScale.id]);
      if (!vScale) return result;

      var parsed = this._cachedMeta._parsed[index];
      var vAxis = (this._cachedMeta.vScale && this._cachedMeta.vScale.axis) || 'y';
      var val = parsed && parsed[vAxis];
      if (val == null) return result;

      var head = vScale.getPixelForValue(val);
      var base = vScale.getPixelForValue(0);
      var size = head - base;
      return { size: size, base: base, head: head, center: base + size / 2 };
    };
  }

  // Apply immediately if Chart is ready, otherwise wait for DOMContentLoaded
  if (Chart.registry && Chart.registry.controllers) {
    applyBarFix();
  }
  document.addEventListener('DOMContentLoaded', applyBarFix);
})();
