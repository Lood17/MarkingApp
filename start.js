module.exports = {
  daemon: true,
  run: [
    {
      method: "local.set",
      params: {
        port: "{{port}}"
      }
    },
    {
      method: "shell.run",
      params: {
        env: { },
        path: "app",
        message: [
          ".venv\\Scripts\\python.exe app.py --host 0.0.0.0 --port {{local.port}}"
        ],
        on: [{
          event: "/(http:\\/\\/[0-9.:]+)/",
          done: true
        }]
      }
    },
    {
      method: "local.set",
      params: {
        url: "http://127.0.0.1:{{local.port}}"
      }
    }
  ]
}
