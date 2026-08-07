const button = document.querySelector('#status');
const message = document.querySelector('#message');

button.addEventListener('click', () => {
  const time = new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' }).format(new Date());
  message.textContent = `Signal received locally at ${time}. JavaScript is running.`;
});
