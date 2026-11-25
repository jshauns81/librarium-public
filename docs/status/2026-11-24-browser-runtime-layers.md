# Source-browser runtime image

The source-browser build copies the sanitized filesystem from the pinned
Chrome distribution into a fresh image. Hosted acceptance checks the layer
count and SSH host identity paths before exercising the existing browser and
sandbox tests.
