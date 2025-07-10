- Anytime you make a change to the data being sent or received, you should follow this process:
  1. Adjust the openapi.yaml file first
  2. Verify the syntax of the openapi.yaml file using `yaml.safe_load`
  3. Regenerate the types following the instructions in the `data_models/README.md` file
  4. Verify the new data model is generated
  5. Verify the syntax of the generated types files
  6. Run formatting and linting on the generated types files
  7. Adjust the `__init__.py` files in the `data_models` directory to match/export the new data model
  8. Only then, make the changes to the rest of the codebase
  9. Run the CI tests to verify that the changes are working
- The comfyui_manager is a python package that is used to manage the comfyui server. There are two sub-packages `glob` and `legacy`. These represent the current version (`glob`) and the previous version (`legacy`), not including common utilities and data models. When developing, we work in the `glob` package. You can ignore the `legacy` package entirely, unless you have a very good reason to research how things were done in the legacy or prior major versions of the package. But in those cases, you should just look for the sake of knowledge or reflection, not for changing code (unless explicitly asked to do so).