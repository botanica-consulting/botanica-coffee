function handleSubmit(event) {
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  const st = document.querySelector('input[name="status"]:checked').value;
  const sw = (st == 'on' ? 'BrewingMode' : 'StandBy');

  event.preventDefault();
  fetch('https://gw-lmz.lamarzocco.io/v1/home/machines/' + username + '/status', {
    method: 'POST',
    headers: {
      // 'accept': '*/*',
      'currentappos': 'ios',
      'content-type': 'application/json',
      // 'accept-language': 'en-IL;q=1, he-IL;q=0.9',
      'authorization': 'Bearer ' + password,
      'currentappversion': '3.1.4',
      'user-agent': 'La Marzocco/3.1.4 (iPhone; iOS 17.5.1; Scale/3.00)'
    },
    body: JSON.stringify({
      'status': sw
    })
  });
}

