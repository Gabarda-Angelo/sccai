<?php
// orderlist.php (POS component)
include_once 'connectdb.php';
session_start();
include_once "header.php";

// Set the default timezone (adjust if needed)
date_default_timezone_set('Asia/Manila');

// Authorization check
if (!isset($_SESSION['email']) || $_SESSION['role'] === 'Cashier') { 
    echo "<script>
            alert('Sorry, you can\'t access this. Please contact the Admin.');
            window.location.href = '../index.php';
          </script>"; 
    exit;
}
?>
<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Content Header (Page header) -->
    <div class="content-header">
        <div class="container-fluid">
            <div class="row mb-2">
                <div class="col-sm-6">
                    <h1 class="m-0">Order History</h1>
                </div>
            </div>
        </div>
    </div>

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="row">
                <div class="col-lg-12">
                    <div class="card card-primary card-outline">
                        <div class="card-header">
                            <h5 class="m-0">Sales Transactions</h5>
                        </div>
                        <div class="card-body">
                            <table class="table table-striped table-hover" id="table_orderlist">
                                <thead>
                                    <tr>
                                        <th>Invoice #</th>
                                        <th>Date</th>
                                        <th>Total</th>
                                        <th>Paid</th>
                                        <th>Due</th>
                                        <th>Payment Method</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php
                                    // Using IFNULL to fall back to the original date if CONVERT_TZ returns NULL.
                                    $stmt = $pdo->prepare("
                                        SELECT 
                                            invoice_id, 
                                            IFNULL(
                                                DATE_FORMAT(CONVERT_TZ(order_date, 'UTC', 'Asia/Manila'), '%M %d, %Y'),
                                                DATE_FORMAT(order_date, '%M %d, %Y')
                                            ) AS order_date,
                                            total,
                                            paid,
                                            due,
                                            payment_type
                                        FROM invoices 
                                        ORDER BY invoice_id DESC
                                    ");
                                    $stmt->execute();

                                    // Note: The match expression is available in PHP 8+
                                    while ($row = $stmt->fetch(PDO::FETCH_OBJ)) {
                                        $paymentBadge = match($row->payment_type) {
                                            'Cash'  => 'warning',
                                            'Card'  => 'success',
                                            'Check' => 'danger',
                                            default => 'secondary'
                                        };
                                    ?>
                                    <tr>
                                        <td><?= $row->invoice_id ?></td>
                                        <td><?= $row->order_date ?></td>
                                        <td>₱ <?= number_format($row->total, 2) ?></td>
                                        <td>₱ <?= number_format($row->paid, 2) ?></td>
                                        <td>₱ <?= number_format($row->due, 2) ?></td>
                                        <td>
                                            <span class="badge badge-<?= $paymentBadge ?>">
                                                <?= $row->payment_type ?>
                                            </span>
                                        </td>
                                        <td>
                                            <div class="btn-group">
                                                <a href="printbill.php?id=<?= $row->invoice_id ?>" 
                                                   class="btn btn-sm btn-warning" 
                                                   target="_blank"
                                                   data-toggle="tooltip" 
                                                   title="Print Receipt">
                                                    <i class="fas fa-print"></i>
                                                </a>
                                                <a href="editorderpos.php?id=<?= $row->invoice_id ?>" 
                                                   class="btn btn-sm btn-info"
                                                   data-toggle="tooltip" 
                                                   title="Edit Order">
                                                    <i class="fas fa-edit"></i>
                                                </a>
                                                <button class="btn btn-sm btn-danger btndelete" 
                                                        data-id="<?= $row->invoice_id ?>"
                                                        data-toggle="tooltip" 
                                                        title="Delete Order">
                                                    <i class="fas fa-trash"></i>
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                    <?php 
                                    } 
                                    ?>
                                </tbody>
                            </table>
                        </div><!-- /.card-body -->
                    </div><!-- /.card -->
                </div><!-- /.col-lg-12 -->
            </div><!-- /.row -->
        </div><!-- /.container-fluid -->
    </div><!-- /.content -->
</div><!-- /.content-wrapper -->

<?php include_once "footer.php"; ?>

<!-- Scripts -->
<script>
$(document).ready(function() {
    // Initialize DataTable
    $('#table_orderlist').DataTable({
        order: [[0, 'desc']],
        columnDefs: [
            { targets: [6], orderable: false }
        ]
    });

    // Delete confirmation handler
    $('.btndelete').click(function() {
        const invoiceId = $(this).data('id');
        const $row = $(this).closest('tr');

        Swal.fire({
            title: 'Confirm Deletion',
            text: 'This will permanently delete the order record!',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Delete',
            cancelButtonText: 'Cancel',
            confirmButtonColor: '#d33'
        }).then((result) => {
            if (result.isConfirmed) {
                $.ajax({
                    url: 'orderdelete.php',
                    method: 'POST',
                    data: { pidd: invoiceId },
                    dataType: 'json'
                })
                .done(function(response) {
                    if (response.status === 'success') {
                        $row.fadeOut();
                        Swal.fire('Deleted!', response.message, 'success');
                    } else {
                        Swal.fire('Error!', response.message, 'error');
                    }
                })
                .fail(function() {
                    Swal.fire('Error!', 'Failed to process request', 'error');
                });
            }
        });
    });

    // Initialize tooltips
    $('[data-toggle="tooltip"]').tooltip();
});
</script>
