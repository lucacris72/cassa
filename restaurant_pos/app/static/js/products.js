document.querySelectorAll("[data-bulk-select-group]").forEach((toggle) => {
  toggle.addEventListener("change", () => {
    const group = toggle.dataset.bulkSelectGroup;
    document.querySelectorAll(`[data-bulk-product-checkbox="${group}"]`).forEach((checkbox) => {
      checkbox.checked = toggle.checked;
    });
  });
});
