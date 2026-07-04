const reservationBulkToggle = document.querySelector("[data-bulk-reservations-toggle]");

if (reservationBulkToggle) {
  reservationBulkToggle.addEventListener("change", () => {
    document.querySelectorAll("[data-bulk-reservation-checkbox]").forEach((checkbox) => {
      checkbox.checked = reservationBulkToggle.checked;
    });
  });
}
