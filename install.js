module.exports = {
  run: [
    {
      method: "shell.run",
      params: {
        path: "app",
        message: [
          "uv venv --clear .venv",
          "uv pip install --python .venv\\Scripts\\python.exe -r requirements.txt"
        ]
      }
    }
  ]
}
