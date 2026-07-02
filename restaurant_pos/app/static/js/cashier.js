const cart = [];

function money(cents) {
  return `${(cents / 100).toFixed(2)} EUR`;
}

function cartTotal() {
  return cart.reduce((sum, item) => sum + item.price_cents * item.quantity, 0);
}

function renderCart() {
  const cartItems = document.getElementById("cart-items");
  const cartTotalEl = document.getElementById("cart-total");
  cartItems.innerHTML = "";

  if (cart.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-cart";
    empty.textContent = "Carrello vuoto";
    cartItems.appendChild(empty);
  }

  cart.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "cart-row";

    const main = document.createElement("div");
    main.className = "cart-row-main";

    const title = document.createElement("div");
    title.innerHTML = `<div class="cart-row-title">${item.name}</div><div>${money(item.price_cents * item.quantity)}</div>`;
    if (item.notes) {
      const note = document.createElement("div");
      note.className = "cart-row-note";
      note.textContent = item.notes;
      title.appendChild(note);
    }

    const controls = document.createElement("div");
    controls.className = "qty-controls";
    controls.innerHTML = `
      <button class="icon-button" type="button" data-action="minus" data-index="${index}">-</button>
      <strong>${item.quantity}</strong>
      <button class="icon-button" type="button" data-action="plus" data-index="${index}">+</button>
      <button class="button small" type="button" data-action="note" data-index="${index}">Nota</button>
      <button class="button small danger" type="button" data-action="remove" data-index="${index}">Rimuovi</button>
    `;

    main.appendChild(title);
    main.appendChild(controls);
    row.appendChild(main);
    cartItems.appendChild(row);
  });

  cartTotalEl.textContent = money(cartTotal());
}

function addProduct(button) {
  const productId = Number(button.dataset.productId);
  const existing = cart.find((item) => item.product_id === productId && !item.notes);
  if (existing) {
    existing.quantity += 1;
  } else {
    cart.push({
      product_id: productId,
      name: button.dataset.name,
      price_cents: Number(button.dataset.priceCents),
      quantity: 1,
      notes: "",
    });
  }
  renderCart();
}

document.querySelectorAll("[data-product-button]").forEach((button) => {
  button.addEventListener("click", () => addProduct(button));
});

document.querySelectorAll("[data-category-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    const filter = button.dataset.categoryFilter;
    document.querySelectorAll("[data-category-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    document.querySelectorAll("[data-product-button]").forEach((product) => {
      const hidden = filter !== "all" && product.dataset.categoryId !== filter;
      product.hidden = hidden;
      product.classList.toggle("is-hidden", hidden);
    });
  });
});

document.getElementById("cart-items").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const index = Number(button.dataset.index);
  const item = cart[index];
  if (!item) return;

  if (button.dataset.action === "plus") item.quantity += 1;
  if (button.dataset.action === "minus") item.quantity -= 1;
  if (button.dataset.action === "remove") cart.splice(index, 1);
  if (button.dataset.action === "note") {
    const note = window.prompt("Nota riga", item.notes || "");
    if (note !== null) item.notes = note.trim();
  }
  if (item.quantity <= 0) cart.splice(index, 1);
  renderCart();
});

document.getElementById("clear-cart").addEventListener("click", () => {
  cart.splice(0, cart.length);
  renderCart();
});

document.getElementById("order-form").addEventListener("submit", (event) => {
  if (cart.length === 0) {
    event.preventDefault();
    window.alert("Il carrello e vuoto");
    return;
  }
  document.getElementById("cart-json").value = JSON.stringify(
    cart.map((item) => ({
      product_id: item.product_id,
      quantity: item.quantity,
      notes: item.notes,
    })),
  );
});

renderCart();
