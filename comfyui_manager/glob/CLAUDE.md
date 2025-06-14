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
