import gradio as gr

with gr.Blocks() as app:
    gr.Markdown("# NyankoFace Space")
    gr.Textbox(label="入力")

app.launch(server_name="0.0.0.0", server_port=7860)
