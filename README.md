<div align="center" style="text-align:center; width: 100%">

# Bomnado 🌪️

**A Bill of Materials (BOM) management system for organising parts, assemblies, and manufacturing data**

</div>



<div align="center">

  [🏃‍➡️ Quick start](#quick-start)&emsp;
  [🛠️ Development](#development)&emsp;
  [🚀 Deployment](#deployment)&emsp;
  [✋ Contributing](#contributing)&emsp;
  [📃 License](#license)&emsp;

</div>

<div align="center">

  Built with ❤︎ by [HE Inventions](https://heinventions.com)

</div>

----

## Features

- **Parts management** - Track part specifications, suppliers, pricing, and inventory
- **Assembly hierarchy** - Build complex BOMs with nested subassemblies  
- **Team collaboration** - Multi-user access with team-based permissions
- **File attachments** - Support for images, documents, and CAD files
- **Export & reports** - Generate Excel spreadsheets and purchasing lists
- **REST API** - Full API access for integrations and automation
- **Search & filter** - Find parts and assemblies across your entire database

## Quick start

**Local evaluation** (requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)):

```powershell
# Launch with Docker
docker compose -f docker-compose.eval.yml up -d --build

# Open http://127.0.0.1:8000 and create your first user account
```

> **⚠️ Warning**: This uses default settings and should not be used in production.

## Development

### Prerequisites

- Python 3.12+
- [PDM](https://pdm-project.org/en/latest/) for dependency management

*Note: Development uses SQLite by default; production deployments prefer PostgreSQL.*

### Setup

```powershell
# Install dependencies
pdm install

# Set up environment
cp .env.eval.example .env

# Generate secret key
pdm run ./generate_secret_key.py -o .env

# Start development server
pdm run manage runserver
```

Open http://127.0.0.1:8000 to access Bomnado.

### Development commands

```powershell
# Run database migrations (can be done via the browser during first run)
pdm run migrate

# Create superuser (can be done via the browser during first run)
pdm run manage createsuperuser

# Run tests
pdm run test

# Create demo data
pdm run manage createdemo

# Django shell
pdm run manage shell

# Collect static files
pdm run manage collectstatic
```

## Deployment

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for detailed configuration options.

## Contributing

Want to help improve Bomnado? See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup and contribution guidelines.

## License

This project is licensed under the MIT License - see the [`LICENSE`](LICENSE) file for details.
