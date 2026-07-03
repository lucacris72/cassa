const pendingCart = (window.pendingOrderItems || []).filter((item) => item.product_id);

function pendingMoney(cents) {
  return `${(cents / 100).toFixed(2)} EUR`;
}

function pendingCartTotal() {
  return pendingCart.reduce((sum, item) => sum + item.price_cents * item.quantity, 0);
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value || "";
  return div.innerHTML;
}

function renderPendingCart() {
  const container = document.getElementById("pending-order-items");
  container.innerHTML = "";

  pendingCart.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "pending-order-row";
    row.innerHTML = `
      <div class="pending-product">
        <strong>${escapeHtml(item.name)}</strong>
        <span>${pendingMoney(item.price_cents)} cad. · ${pendingMoney(item.price_cents * item.quantity)}</span>
      </div>
      <label>
        Qta
        <input type="number" min="1" value="${item.quantity}" data-action="quantity" data-index="${index}">
      </label>
      <label>
        Nota
        <input value="${escapeHtml(item.notes)}" data-action="notes" data-index="${index}">
      </label>
      <button class="button danger" type="button" data-action="remove" data-index="${index}">Rimuovi</button>
    `;
    container.appendChild(row);
  });

  const total = document.createElement("div");
  total.className = "pending-total";
  total.innerHTML = `<span>Totale aggiornato</span><strong>${pendingMoney(pendingCartTotal())}</strong>`;
  container.appendChild(total);
}

function addPendingProduct() {
  const select = document.getElementById("pending-product-select");
  const option = select.selectedOptions[0];
  const quantityInput = document.getElementById("pending-product-quantity");
  const quantity = Math.max(1, Number(quantityInput.value || 1));
  const productId = Number(option.value);
  const existing = pendingCart.find((item) => item.product_id === productId && !item.notes);
  if (existing) {
    existing.quantity += quantity;
  } else {
    pendingCart.push({
      product_id: productId,
      name: option.dataset.name,
      price_cents: Number(option.dataset.priceCents),
      quantity,
      notes: "",
    });
  }
  quantityInput.value = "1";
  renderPendingCart();
}

document.getElementById("pending-order-items").addEventListener("change", (event) => {
  const input = event.target.closest("[data-action]");
  if (!input) return;
  const item = pendingCart[Number(input.dataset.index)];
  if (!item) return;
  if (input.dataset.action === "quantity") {
    item.quantity = Math.max(1, Number(input.value || 1));
  }
  if (input.dataset.action === "notes") {
    item.notes = input.value.trim();
  }
  renderPendingCart();
});

document.getElementById("pending-order-items").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action='remove']");
  if (!button) return;
  pendingCart.splice(Number(button.dataset.index), 1);
  renderPendingCart();
});

document.getElementById("pending-add-product").addEventListener("click", addPendingProduct);

document.getElementById("pending-order-form").addEventListener("submit", (event) => {
  if (pendingCart.length === 0) {
    event.preventDefault();
    window.alert("La comanda non puo essere vuota");
    return;
  }
  document.getElementById("pending-cart-json").value = JSON.stringify(
    pendingCart.map((item) => ({
      product_id: item.product_id,
      quantity: item.quantity,
      notes: item.notes,
    })),
  );
});

renderPendingCart();
