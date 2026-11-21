import '@testing-library/jest-dom/vitest'

// jsdom has <dialog> but not its methods (yet). A minimal stand-in: open and
// close toggle the `open` attribute, which is what makes it visible.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.open = false
  }
}
