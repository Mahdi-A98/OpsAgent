class DatabaseManager:
    def __init__(self, docker_manager):
        self.docker = docker_manager

    def create_postgres_db(self, db_name, container_name="postgres_db"):
        # Start container if not running
        stdout, stderr = self.docker.run_container(
            image="postgres:15",
            name=container_name,
            ports={"5432": "5432"},
            env={"POSTGRES_PASSWORD": "securepass"}
        )
        print(stdout, stderr)
        # Create database
        cmd = f'psql -U postgres -c "CREATE DATABASE {db_name};"'
        stdout, stderr = self.docker.exec_command(container_name, cmd)
        return stdout, stderr

    def drop_postgres_db(self, db_name, container_name="postgres_db"):
        cmd = f'psql -U postgres -c "DROP DATABASE {db_name};"'
        stdout, stderr = self.docker.exec_command(container_name, cmd)
        return stdout, stderr
