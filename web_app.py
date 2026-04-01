from flask import Flask, render_template, request

from ipl_predictor import load_models, load_support_tables, predict_match_state


app = Flask(__name__)

score_model, win_model = load_models()
support_tables = load_support_tables()


@app.route("/", methods=["GET", "POST"])
def index():
    prediction = None
    errors: list[str] = []
    form_data = {}

    if request.method == "POST":
        form_data = request.form.to_dict()
        prediction, errors = predict_match_state(
            form_data,
            support_tables=support_tables,
            score_model=score_model,
            win_model=win_model,
        )

    return render_template(
        "index.html",
        prediction=prediction,
        errors=errors,
        form_data=form_data,
    )


if __name__ == "__main__":
    app.run(debug=True)
