from flask import Flask, request
import logging

app = Flask(__name__)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
app.logger.addHandler(handler)


@app.route('/webhook', methods=['POST'])
def webhook():
    # store last received body (as text) for CI to poll
    body = request.get_data(as_text=True)
    app.logger.info('Received webhook: headers=%s body=%s', dict(request.headers), body)
    app.config['LAST_WEBHOOK'] = body
    return ('', 204)


@app.route('/last', methods=['GET'])
def last():
    # return last received webhook body (or empty) as plain text
    last = app.config.get('LAST_WEBHOOK')
    if not last:
        return ('', 204)
    return (last, 200, {'Content-Type': 'application/json'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
