# Contributing

## Reporting Issues

Open a GitHub issue with:
- A clear description of the problem or suggestion
- Relevant error messages or log output
- Python version

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b my-feature`)
3. Make your changes and test locally
4. Commit with a clear message and open a pull request against `main`

## Development Notes

- **Language:** Python 3
- Depends on Google Calendar API and Facebook Graph API credentials (not included in repo)
- Copy `fb_config.example.json` to `fb_config.local.json` and add your credentials
- Never commit API keys, secrets, or credential files
- Test with your own API credentials; CI does not have access to live APIs

## Code Style

- Follow PEP 8
- Keep functions focused and well-named
- Avoid adding dependencies unless necessary

## License

By contributing, you agree that your contributions will be licensed under the project's existing license.
