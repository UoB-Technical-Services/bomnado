# Contributing to Bomnado

This project is open source to support small and medium-sized enterprises in managing production and manufacturing. We welcome contributions! 🛠️

## Getting started

For development setup, see the [Development section](README.md#development) in the main readme.

### Testing changes
```powershell
# Run code quality checks
pdm run flake8

# Run tests
pdm run test
```

## Ways to contribute
- Report bugs
- Suggest features or improvements
- Contribute code (bugfixes, enhancements, documentation)
- Improve tests and deployment configurations

## Submitting changes
- Create a new branch: `git checkout -b feature/your-feature`
- Commit your changes with clear messages
- Push your branch and open a Pull Request
- Be descriptive — tell us what problem this solves

## Questions or ideas?
Open an [issue](/issues) to ask questions about why things have been done if you think they could be improved. We adopt a [Chesterton's Fence](https://en.wiktionary.org/wiki/Chesterton%27s_fence) mentality when developing: don't assume something should be removed if you don't understand why it's there to begin with.


## GitHub Container Registry

Tagging a commit on the `main` branch with a version — e.g. `v0.19.0` — will trigger an optional action that pushes the Bomnado Docker image to the [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry). Future deployments may be more efficient if they use images from here instead of building from source.
